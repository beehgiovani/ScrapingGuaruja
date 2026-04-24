import sys
sys.stdout.reconfigure(encoding='utf-8')
print("--- Bot Process Starting ---", flush=True)

import asyncio
from playwright.async_api import async_playwright
print("--- Playwright Imported ---", flush=True)

# import ddddocr (Moved to Lazy Load)
# print("--- OCR Imported ---", flush=True)

import os
import requests
import re
import tempfile
import shutil
import time
import random
import uuid

from data_normalizer import normalize_lot_data, is_valid_lot
from tor_manager import TorManager
from proxy_config import get_proxy_for_worker

print("--- Imports Done ---", flush=True)

# Inicializar o resolver de captcha do ddddocr (PRE-LOAD with stagger)
ocr_instance = None

def preload_ddddocr(worker_id=0):
    """Pre-loads ddddocr with file locking to avoid simultaneous loading."""
    global ocr_instance
    if ocr_instance is None:
        lock_file = "ddddocr_loading.lock"
        start_wait = time.time()
        
        while True:
            try:
                # Try to create lock file atomically
                fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.close(fd)
                break # Lock acquired
            except FileExistsError:
                # Check for stale lock (older than 60s)
                try:
                    if os.path.exists(lock_file):
                        if time.time() - os.path.getmtime(lock_file) > 60:
                            print("Removing stale lock file...", flush=True)
                            os.remove(lock_file)
                            continue
                except: pass
                
                # Check for timeout waiting
                if time.time() - start_wait > 300: # 5 min total timeout
                    print("Timeout waiting for ddddocr lock. Proceeding anyway...", flush=True)
                    break 
                
                time.sleep(random.uniform(0.5, 1.5))
            except Exception as e:
                print(f"Lock error: {e}", flush=True)
                break

        try:
            print("Loading ddddocr (Safe Mode)...", flush=True)
            import ddddocr
            ocr_instance = ddddocr.DdddOcr(show_ad=False)
            print("✓ ddddocr loaded successfully.", flush=True)
        except Exception as e:
            print(f"Error loading ddddocr: {e}", flush=True)
        finally:
            # Release lock
            try:
                if os.path.exists(lock_file):
                    os.remove(lock_file)
            except: pass

async def solve_captcha(page, img_selector):
    """Tenta resolver o captcha de imagem usando ddddocr (OCR gratuito e offline)."""
    global ocr_instance
    if ocr_instance is None:
        # Fallback if not pre-loaded (shouldn't happen)
        print("WARNING: ddddocr not pre-loaded. Loading now...", flush=True)
        import ddddocr
        ocr_instance = ddddocr.DdddOcr(show_ad=False)
        print("ddddocr loaded.", flush=True)

    try:
        print("Detectando captcha...")
        img_element = await page.wait_for_selector(img_selector, timeout=5000)
        img_bytes = await img_element.screenshot()
        captcha_text = ocr_instance.classification(img_bytes)
        print(f"Captcha detectado: {captcha_text}")
        return captcha_text
    except Exception as e:
        print(f"Erro ao resolver captcha: {e}")
        return ""

async def handle_captcha_flow(page, next_selector):
    """Tenta resolver o captcha repetidamente até que o próximo seletor apareça ou exceda o limite."""
    max_attempts = int(os.getenv("CAPTCHA_ATTEMPTS", 15))
    for attempt in range(max_attempts):
        # 1. Verificar se já passamos (seletor alvo visível)
        if await page.query_selector(next_selector):
            print("Captchar superado ou inexistente.")
            return True

        # 2. Verificar presença do captcha
        captcha_img = await page.query_selector('img[src*="digits"]')
        
        if captcha_img:
            print(f"Captcha encontrado. Tentativa {attempt+1}/{max_attempts}...")
            captcha_text = await solve_captcha(page, 'img[src*="digits"]')
            
            if captcha_text:
                await page.fill('#DigitDigits', captcha_text)
                await page.click('input[type="submit"]')
                
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except:
                    pass
                await asyncio.sleep(1)
            else:
                print("OCR retornou vazio. Tentando recarregar imagem...")
                await page.reload()
                await page.wait_for_load_state("networkidle")
        else:
            print("Aguardando carregamento da página...")
            await asyncio.sleep(2)
            
    return await page.query_selector(next_selector) is not None

async def extract_popup_url(page, link_selector):
    """Extrai a URL relativa de um link com javascript:openWindowScrollable."""
    try:
        element = await page.wait_for_selector(link_selector, timeout=5000)
        href = await element.get_attribute('href')
        # Regex para pegar o primeiro argumento da função JS: '/caminho/...'
        match = re.search(r"openWindowScrollable\('([^']+)'", href)
        if match:
            return match.group(1)
    except:
        return None
    return None

def atomic_write_json(data, filename):
    """
    Writes JSON to a temp file and then atomically renames it to the target filename.
    Includes retry logic for Windows file locking issues.
    """
    import json
    dir_name = os.path.dirname(os.path.abspath(filename))
    base_name = os.path.basename(filename)
    
    # Create temp file in same directory
    with tempfile.NamedTemporaryFile(mode='w', delete=False, dir=dir_name, encoding='utf-8', suffix='.tmp', prefix=f"tmp_{base_name}_") as tf:
        json.dump(data, tf, indent=4, ensure_ascii=False)
        temp_name = tf.name
        # Flush and sync to ensure data is on disk
        tf.flush()
        os.fsync(tf.fileno())
    
    # Retry loop for rename
    max_retries = 5
    for attempt in range(max_retries):
        try:
            os.replace(temp_name, filename)
            return True
        except PermissionError:
            if attempt < max_retries - 1:
                time.sleep(0.1) # Wait a bit
                continue
            else:
                print(f"FAILED to update {filename} after {max_retries} attempts due to lock.")
        except Exception as e:
             print(f"Error atomic writing {filename}: {e}")
             break
    
    # If we failed to rename, try to clean up temp
    try:
        if os.path.exists(temp_name):
            os.remove(temp_name)
    except: pass
    return False

async def run():
    import sys
    import argparse
    import json
    
    # --- 1. PRE-CONFIGURATION & DATA LOADING ---
    
    # 1. Parse Args First (Moved to fix scope)
    parser = argparse.ArgumentParser()
    parser.add_argument('--shard', type=int, default=0, help='Shard index (0-based)')
    parser.add_argument('--total', type=int, default=1, help='Total number of shards')
    args, _ = parser.parse_known_args()
    
    shard_idx = args.shard
    total_shards = args.total

    # PRE-LOAD ddddocr with staggered delay to avoid deadlock
    preload_ddddocr(shard_idx)

    # === HTTP PROXY CONFIGURATION ===
    # === HTTP PROXY CONFIGURATION ===
    use_proxy = os.getenv("USE_PROXY_GLOBAL", os.getenv("USE_PROXY", "false")).lower() == "true"
    proxy_config = None
    
    if use_proxy:
        print("=== HTTP Proxy Enabled ===")
        try:
            proxy_info = get_proxy_for_worker(shard_idx)
            proxy_config = {
                'http': proxy_info['http'],
                'https': proxy_info['https']
            }
            print(f"--- Worker {shard_idx} using HTTP Proxy: {proxy_info['host_port']} ---")
            
            # Test proxy
            try:
                ip_response = requests.get("https://ipv4.webshare.io/", proxies=proxy_config, timeout=15)
                proxy_ip = ip_response.text.strip()
                print(f"Worker {shard_idx} Proxy IP: {proxy_ip}")
                print("✓ Proxy working")
            except Exception as e:
                print(f"⚠ Warning: Proxy test failed: {e}")
                print("Will proceed anyway...")
        except Exception as e:
            print(f"❌ Error loading proxy config: {e}")
            use_proxy = False
        
        print("===================================")

    # 2. Config - TOR (Legacy, disabled when HTTP proxy is active)
    tor = TorManager()
    # Disable Tor if HTTP proxy is enabled (can't use both)
    use_tor = os.getenv("USE_TOR", "true").lower() == "true" and not use_proxy
    
    if use_tor:
        print("=== Tor IP Masking Enabled ===")
        # [NEW] Use STANDARD Tor Port (9050) as requested
        # We still use custom username/pass for isolation
        assigned_socks_port = 9152
        print(f"--- Worker {shard_idx} using STANDARD Tor Port: {assigned_socks_port} ---")
        
        if not tor.start():
            print("⚠ WARNING: Failed to start Tor. Proceeding without IP masking.")
            use_tor = False
        else:
            # Check IP via the assigned port
            try:
                proxies = {
                    'http': f'socks5h://127.0.0.1:{assigned_socks_port}',
                    'https': f'socks5h://127.0.0.1:{assigned_socks_port}'
                }
                
                # Increased timeout to 30s
                ip_response = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=30)
                real_ip = ip_response.json()["ip"]
                
                print(f"Worker {shard_idx} Tor IP: {real_ip}")
                print("✓ IP successfully masked")
            except Exception as e:
                print(f"Error getting IP on port {assigned_socks_port}: {e}")
                print("Tor IP: None (Will retry in browser)")
            
            print("===================================")

    # Duplicate code removed

    # === CRITICAL SAFETY CHECK - DISABLED ===
    # Comentado temporariamente porque api.ipify.org está com timeout
    # O Tor está rodando (tor.start() = True), então vamos confiar nisso
    # if use_tor:
    #     print("=== Tor IP Masking Enabled ===")
    #     assigned_socks_port = 9150
    #     print(f"--- Worker {shard_idx} using STANDARD Tor Port: {assigned_socks_port} ---")
    #     
    #     if not tor.start():
    #         print("⚠ WARNING: Failed to start Tor. Proceeding without IP masking.")
    #         use_tor = False
    #     else:
    #         # SECOND ATTEMPT - CRITICAL CHECK
    #         try:
    #             proxies = {
    #                 'http': f'socks5h://127.0.0.1:{assigned_socks_port}',
    #                 'https': f'socks5h://127.0.0.1:{assigned_socks_port}'
    #             }
    #             
    #             # Increased timeout to 60s for second attempt
    #             ip_response = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=60)
    #             real_ip = ip_response.json()["ip"]
    #             
    #             print(f"Worker {shard_idx} Tor IP: {real_ip}")
    #             print("✓ IP successfully masked")
    #         except Exception as e:
    #             print(f"❌ CRITICAL: Error getting IP on port {assigned_socks_port} (2nd attempt): {e}")
    #             print("❌ SAFETY GUARD: Cannot verify Tor connection. EXITING to prevent real IP exposure.")
    #             print("❌ Please check Tor service manually before restarting.")
    #             sys.exit(1)  # HARD EXIT
    #         
    #         print("===")


    # Load Lotes
    input_file = 'data/entrada_lotes.json'
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
    except FileNotFoundError:
        print(f"Arquivo de entrada '{input_file}' não encontrado.")
        return

    if isinstance(raw_data, dict) and 'data' in raw_data:
        all_lotes = list(raw_data['data'].values())
    elif isinstance(raw_data, list):
        all_lotes = raw_data
    else:
        all_lotes = []
        print(f"Formato de dados inesperado. Saindo.")
        return

        return

    # === [NEW] FILTER BY ZONES ===
    target_zones_env = os.getenv("TARGET_ZONES", "")
    if target_zones_env and target_zones_env != "":
        target_zones = [z.strip() for z in target_zones_env.split(",")]
        print(f"Applying Zone Filter: {target_zones}")
        
        filtered_lotes = []
        for l in all_lotes:
             # Check top level 'zona' first, then 'metadata.zona'
             z = str(l.get('zona', '') or '')
             
             # Safely check metadata if z is empty
             if not z:
                 meta = l.get('metadata')
                 if meta and isinstance(meta, dict):
                     z = str(meta.get('zona', '') or '')
             
             if z in target_zones:
                 filtered_lotes.append(l)
                 
        all_lotes = filtered_lotes
        print(f"Filtered to {len(all_lotes)} lots matching zones.")

    # Sharding
    if total_shards > 1:
        all_lotes = all_lotes[shard_idx::total_shards]
        print(f"--- Worker {shard_idx}: Processando {len(all_lotes)} lotes (Sharding {shard_idx}/{total_shards}) ---")

    # Normalize Data
    lotes_para_processar = []
    for l in all_lotes:
        normalized = normalize_lot_data(l)
        if normalized['zona'] and normalized['setor'] and normalized['loteGeo']:
            l['zona'] = normalized['zona']
            l['setor'] = normalized['setor']
            l['loteGeo'] = normalized['loteGeo']
            l['quadra'] = normalized['quadra']
            l['lote'] = normalized['lote']
            lotes_para_processar.append(l)

    print(f"Iniciando Worker {shard_idx}. Lotes Válidos: {len(lotes_para_processar)}")

    # Prepare Output Files
    suffix = f"_part{shard_idx}" if total_shards > 1 else ""
    output_file = f'data/saida_imoveis{suffix}.json'
    legacy_file = 'data/saida_imoveis.json'
    
    dados_extraidos = []
    lotes_processados_ids = set()
    
    # Load Existing/Legacy
    exec_mode = os.getenv("EXECUTION_MODE", "SMART_RESUME")
    print(f"Modo de Execução: {exec_mode}")

    statuses_to_skip = []
    if exec_mode == "FAST_RESUME":
        statuses_to_skip = ['sucesso', 'sem_boleto', 'sucesso_parcial', 'sucesso_certidao_apenas', 'sucesso_certidao_sem_boleto', 'sucesso_desmembrado', 'anulada']
    elif exec_mode == "SMART_RESUME":
        statuses_to_skip = ['sucesso', 'sucesso_parcial', 'sucesso_certidao_apenas', 'sucesso_desmembrado', 'sucesso_certidao_sem_boleto', 'anulada']
    elif exec_mode == "REPROCESS_ALL":
        statuses_to_skip = []
    else:
        statuses_to_skip = ['sucesso'] # Default Smart

    # --- REPROCESS FLAGS & UPDATE MODE ---
    reprocess_flags_str = os.environ.get("REPROCESS_FLAGS", "")
    reprocess_flags = [x.strip().lower() for x in reprocess_flags_str.split(",") if x.strip()]
    
    update_mode = "update_mode" in reprocess_flags
    reprocess_anulados = "anulados" in reprocess_flags
    reprocess_erros = "erros" in reprocess_flags
    reprocess_sem_boleto = "sem_boleto" in reprocess_flags
    reprocess_desmembrados = "desmembrados" in reprocess_flags
    reprocess_more_subunits = "more_subunits" in reprocess_flags

    if update_mode:
        print("⚡ UPDATE MODE ACTIVE: Will re-verify successful records.")
        # If updating, we DON'T skip successes.
        if 'sucesso' in statuses_to_skip: statuses_to_skip.remove('sucesso')
        if 'sucesso_desmembrado' in statuses_to_skip: statuses_to_skip.remove('sucesso_desmembrado')
        if 'sucesso_parcial' in statuses_to_skip: statuses_to_skip.remove('sucesso_parcial')
        if 'sucesso_certidao_apenas' in statuses_to_skip: statuses_to_skip.remove('sucesso_certidao_apenas')
    
    if reprocess_anulados and 'anulada' in statuses_to_skip: statuses_to_skip.remove('anulada')
    if reprocess_erros:
        # Erros usually aren't in skip list, but good to ensure
        pass 
    if reprocess_sem_boleto:
        if 'sem_boleto' in statuses_to_skip: statuses_to_skip.remove('sem_boleto')
        if 'sucesso_certidao_sem_boleto' in statuses_to_skip: statuses_to_skip.remove('sucesso_certidao_sem_boleto')
    if reprocess_desmembrados:
         if 'sucesso_desmembrado' in statuses_to_skip: statuses_to_skip.remove('sucesso_desmembrado')

    print(f"📋 Statuses to SKIP: {statuses_to_skip}")
    
    # 1. Load Legacy Data (to skip what was already done before sharding)
    if os.path.exists(legacy_file):
        try:
            with open(legacy_file, 'r', encoding='utf-8') as f:
                legacy_data = json.load(f)
                skipped_legacy_count = 0
                for item in legacy_data:
                     status_raw = item.get('status_processamento', '')
                     status_clean = status_raw.strip() if status_raw else ''
                     if item.get('inscricao') and status_clean in statuses_to_skip:
                        lotes_processados_ids.add(item['inscricao'])
                        skipped_legacy_count += 1
                print(f"  -> Carregados {skipped_legacy_count} itens ignorados do arquivo LEGADO ({legacy_file}).")
        except: pass

    # 2. Load Shard Data (resume this specific worker)
    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                conteudo_existente = json.load(f)
                
                dados_extraidos = []
                for item in conteudo_existente:
                    status_raw = item.get('status_processamento', '')
                    status_clean = status_raw.strip() if status_raw else ''
                    
                    if item.get('inscricao') and status_clean in statuses_to_skip:
                        lotes_processados_ids.add(item['inscricao'])
                        dados_extraidos.append(item)

                        
            print(f"Retomando execução. Carregados {len(dados_extraidos)} lotes VÁLIDOS/PULADOS de {output_file}.")
            
        except json.JSONDecodeError:
            print("Arquivo de saída corrompido ou vazio. Iniciando do zero.")
            dados_extraidos = []

    if not os.path.exists(output_file):
         atomic_write_json(dados_extraidos, output_file)

    # --- 2. BROWSER LIFECYCLE MANAGEMENT ---
    
    async with async_playwright() as p:
        browser = None
        context = None
        page = None
        
        # State for IP Rotation
        rotation_counter = 0
        last_rotation_time = 0
        
        async def rotate_browser_session():
            """Closes current browser and starts a new one with a fresh Tor identity (Port-based)."""
            nonlocal browser, context, page, rotation_counter, last_rotation_time
            
            if browser:
                try: await browser.close()
                except: pass
            
            rotation_counter += 1
            if rotation_counter > 1:
                print(f"♻️  ROTATING BROWSER (Session {rotation_counter}) ...")
            
            launch_options = {'headless': os.getenv("HEADLESS_MODE", "true").lower() == "true"}
            
            # HTTP Proxy Configuration (Webshare.io)
            if use_proxy and proxy_config:
                try:
                    # Playwright requires server and credentials separately
                    # Pass rotation_counter as attempt to shift file proxy index
                    proxy_info = get_proxy_for_worker(shard_idx, attempt=rotation_counter)
                    proxy_host_port = proxy_info['host_port']
                    proxy_type = proxy_info.get('type', 'webshare')
                    
                    print(f"Note: Connecting via {proxy_type.upper()} Proxy ({proxy_host_port})")
                    
                    # Generate Random Session ID for Bright Data to FORCE new IP
                    session_id = str(uuid.uuid4())[:8]
                    
                    # Playwright proxy format (credentials separate)
                    if proxy_type == 'brightdata1':
                        # Bright Data Zone: Proxys (Datacenter)
                        launch_options['proxy'] = {
                            'server': 'http://brd.superproxy.io:33335',
                            'username': f'brd-customer-hl_292834f5-zone-proxys-session-{session_id}',
                            'password': 'qs4mhcgm3rvc'
                        }
                    elif proxy_type == 'brightdata2':
                        # Bright Data Zone: Residential Proxy 1
                        launch_options['proxy'] = {
                            'server': 'http://brd.superproxy.io:33335',
                            'username': f'brd-customer-hl_292834f5-zone-residential_proxy1-session-{session_id}',
                            'password': 'jxp0okwy4d0l'
                        }
                    elif proxy_type == 'file_proxy':
                        # File List Proxy (SOCKS5/HTTP)
                        scheme = 'socks5' if 'socks' in proxy_info.get('http', '') else 'http'
                        launch_options['proxy'] = {
                            'server': f'{scheme}://{proxy_host_port}'
                        }
                        if proxy_info.get('user'):
                            launch_options['proxy']['username'] = proxy_info['user']
                            launch_options['proxy']['password'] = proxy_info['pass']
                    else:
                        # Webshare datacenter proxy
                        launch_options['proxy'] = {
                            'server': f'http://{proxy_host_port}',
                            'username': 'owoqoswg',
                            'password': 'e6zd34br4bq6'
                        }
                except Exception as e:
                    print(f"Error configuring HTTP proxy: {e}")
            
            # Legacy Tor Configuration (disabled by default)
            if use_tor:
                try:
                    # USE STANDARD TOR PORT
                    socks_port = 9152
                    
                    print(f"Note: Connecting to Standard Tor Port: {socks_port}")
                    
                    # Firefox Prefs for Proxy
                    launch_options['firefox_user_prefs'] = {
                        "network.proxy.type": 1,
                        "network.proxy.socks": "127.0.0.1",
                        "network.proxy.socks_port": socks_port,
                        "network.proxy.socks_version": 5,
                        "network.proxy.socks_remote_dns": True,
                        # Force isolation: Change username to force new circuit
                        # Even though we are on a dedicated port, consistent username 
                        # per session helps keep the circuit stable for THAT session,
                        # and changing it on rotation (rotation_counter) forces a new one.
                        "network.proxy.socks_username": f"bot{shard_idx}_{rotation_counter}",
                        "network.proxy.socks_password": "password"
                    }
                except Exception as e:
                    print(f"Error configuring Tor port: {e}")
            
                except Exception as e:
                    print(f"Error configuring Tor port: {e}")
            
            # [NEW] TOR IP ROTATION
            if use_tor:
                 # Force new circuit (NEWNYM) before Launching
                 # We use the global 'tor' instance created in run()
                 # Ensure proper scoping
                 try:
                     print("Requesting new Tor Identity (IP)...")
                     tor.rotate_ip()
                     # time.sleep(5) # rotate_ip already sleeps 3s
                 except Exception as e:
                     print(f"Error rotating Tor IP: {e}")

            try:
                browser = await p.firefox.launch(**launch_options)
            except Exception as e:
                print(f"Firefox launch failed: {e}. Fallback to Chromium.")
                
                # Chromium proxy config
                if use_tor:
                     socks_port = 9152
                     launch_options['proxy'] = {
                         'server': f'socks5://127.0.0.1:{socks_port}',
                         'username': f'bot{shard_idx}_{rotation_counter}',
                         'password': 'password'
                     }
                
                if 'firefox_user_prefs' in launch_options:
                    del launch_options['firefox_user_prefs']
                    
                browser = await p.chromium.launch(**launch_options)
                
            context = await browser.new_context(ignore_https_errors=True)
            # Increase Timeouts for Tor (was 60s, now 90s/120s)
            context.set_default_timeout(int(os.getenv("DEFAULT_TIMEOUT", 90000)))
            context.set_default_navigation_timeout(120000)
            page = await context.new_page()
            
            # Global Routes
            await page.route("**/*.{png,jpg,jpeg}", lambda route: route.continue_()) 
            await page.route("**/*.{css,woff,woff2}", lambda route: route.continue_())
            
            last_rotation_time = time.time()
            return page

        # Initial Launch
        await rotate_browser_session()
        
        # --- Helper for Single Inscription (Copied/Adapted) ---
        async def process_inscription(inscricao_target, display_name, active_page):
            result = {
                "nome_lote": display_name,
                "inscricao": inscricao_target,
                "status_processamento": "pendente",
                # Init other fields to None
                "cpf_cnpj": None, "nome_proprietario": None, "rua": None, "numero": None,
                "complemento": None, "bairro": None, "cep": None, "endereco": None,
                "metragem": None, "descricao_imovel": None, "valor_venal": None, "valor_venal_edificado": None
            }
            geo_page = active_page
            try:
                # 2. Coletar Área
                try:
                    await geo_page.goto("https://scimpmgsp.geometrus.com.br/mctm_lancamentos/index_certidao_valor_venal", timeout=120000)
                except Exception as e:
                    # Retry once with full reload
                    # User Request: Suppress loud error logs.
                    # print(f"[{inscricao_target}] Nav Error: {e}. Reloading page...") if debug
                    await geo_page.reload()
                    await geo_page.goto("https://scimpmgsp.geometrus.com.br/mctm_lancamentos/index_certidao_valor_venal", timeout=120000)
                
                passou = await handle_captcha_flow(geo_page, '#MctmLancamentoIdentificacao')
                if not passou: raise Exception("Captcha Area Falhou")
                
                await geo_page.fill('#MctmLancamentoIdentificacao', inscricao_target)
                await geo_page.click('input[type="submit"]')
                await geo_page.wait_for_load_state("networkidle")
                
                if await geo_page.query_selector("text=Nenhum registro encontrado"):
                    print(f"[{inscricao_target}] Nenhum registro encontrado. Marcando como anulada.")
                    result["status_processamento"] = "anulada"
                    return result # Early return
                
                # ... Extract Data (Same Logic) ...
                search_text = await geo_page.inner_text('body')
                
                # [NEW] Extract Name from Search Page First
                nome_match_search = re.search(r'Nome\s*\n?\s*(.+?)(?=\n|$)', search_text)

                if nome_match_search:
                    nome_scraped = nome_match_search.group(1).strip()
                    result["nome_proprietario"] = nome_scraped
                    
                    PUBLIC_KEYWORDS = ["FAZENDA", "PREFEITURA", "MUNICÍPIO", "MUNICIPIO", "UNIÃO", "UNIAO", "CDHU", "COHAB"]
                    nome_upper = nome_scraped.upper()
                    if any(k in nome_upper for k in PUBLIC_KEYWORDS):
                            result["status_processamento"] = "sucesso_certidao_apenas"
                            print(f"*** [{inscricao_target}] ÓRGÃO PÚBLICO detectado na busca ({nome_scraped}).")

                rua_match = re.search(r'Rua\s*\n?\s*(.+?)(?=\n|$)', search_text)
                if rua_match: result["rua"] = rua_match.group(1).strip()
                
                numero_match = re.search(r'Número/Empl\.\s*\n?\s*(.+?)(?=\n|$)', search_text)
                if numero_match: result["numero"] = numero_match.group(1).strip()
                
                complemento_match = re.search(r'Complemento\s*\n?\s*(.+?)(?=\n|$)', search_text)
                if complemento_match:
                    comp = complemento_match.group(1).strip()
                    if comp: result["complemento"] = comp
                
                bairro_match = re.search(r'Bairro\s*\n?\s*(.+?)(?=\n|$)', search_text)
                if bairro_match: result["bairro"] = bairro_match.group(1).strip()
                
                cep_match = re.search(r'CEP\s*\n?\s*(\d+)', search_text)
                if cep_match: result["cep"] = cep_match.group(1).strip()
                
                # Montar endereço completo organizado
                partes_endereco = []
                if result["rua"]: partes_endereco.append(result["rua"])
                if result["numero"]: partes_endereco.append(result["numero"])
                if result["complemento"]: partes_endereco.append(result["complemento"])
                
                endereco_linha1 = ", ".join(partes_endereco) if partes_endereco else ""
                
                if result["bairro"]: endereco_linha1 += f" - {result['bairro']}"
                if result["cep"]: endereco_linha1 += f" - CEP {result['cep']}"
                
                result["endereco"] = endereco_linha1 if endereco_linha1 else None # type: ignore
                
                # Extrair Quadra/Lote da tela de pesquisa
                ql_match = re.search(r'Quadra/Lote\s*\n?\s*(.+)', search_text)
                if ql_match:
                        ql_val = ql_match.group(1).strip()
                        result["descricao_imovel"] = ql_val

                # Extrair Valor Venal Edificado
                vve_match = re.search(r'Valor Venal Edificado\s*R\$\s*([\d\.,]+)', search_text)
                if vve_match:
                    result["valor_venal_edificado"] = vve_match.group(1)
                
                # Tentar clicar em "Gerar certidão"
                link_relative = await extract_popup_url(geo_page, "a:has-text('Gerar certidão')")
                
                if link_relative:
                    popup_url = f"https://scimpmgsp.geometrus.com.br{link_relative}"
                    await geo_page.goto(popup_url)
                    await geo_page.wait_for_load_state("networkidle")
                    
                    content_text = await geo_page.inner_text('body')
                    
                    # Extrair Metragem
                    area_match = re.search(r'Área do Terreno:\s*([\d\.,]+)', content_text)
                    if area_match:
                        result["metragem"] = area_match.group(1)
                    
                    # Extrair Descrição do Imóvel
                    desc_match = re.search(r'(Quadra\s*.+?Lote\s*.+?)(?=\n|$|\s{2,})', content_text, re.IGNORECASE)
                    if desc_match:
                        result["descricao_imovel"] = desc_match.group(1).strip()

                    # Extrair Valor Venal
                    vv_match = re.search(r'Valor Venal.*?(?:R\$|R\s\$)\s*([\d\.,]+)', content_text, re.IGNORECASE)
                    if vv_match:
                        result["valor_venal"] = vv_match.group(1).strip()
                    
                    # Extrair Proprietário da Certidão
                    prop_match = re.search(r'Proprietário\(a\)\s+(.+?)(?=\s+sob|\s*$)', content_text)
                    if prop_match:
                        prop_name = prop_match.group(1).strip()
                        result["nome_proprietario"] = prop_name
                        
                        PUBLIC_KEYWORDS = ["FAZENDA", "PREFEITURA", "MUNICÍPIO", "MUNICIPIO", "UNIÃO", "UNIAO", "CDHU", "COHAB"]
                        nome_upper = prop_name.upper()
                        
                        if any(k in nome_upper for k in PUBLIC_KEYWORDS):
                            result["status_processamento"] = "sucesso_certidao_apenas"
                            print(f"*** [{inscricao_target}] ÓRGÃO PÚBLICO (Certidão). Marcando sucesso.")
                
                # Flag to optimize flow
                skip_boleto_search = False
                if result.get("status_processamento") == "sucesso_certidao_apenas":
                    skip_boleto_search = True

                # 3. Coletar Proprietário e CPF - Boletos (If not skipped)
                melhor_candidato = None 
                
                if not skip_boleto_search:
                    await geo_page.goto("https://scimpmgsp.geometrus.com.br/mvia2_boletos/lista")
                
                    passou_captcha_boleto = await handle_captcha_flow(geo_page, '#Mvia2BoletoCdSacado')
                    if not passou_captcha_boleto:
                        raise Exception("Não foi possível passar pelo Captcha do Boleto.")

                    await geo_page.fill('#Mvia2BoletoCdSacado', inscricao_target)
                    await geo_page.click('input[type="submit"]')
                    await geo_page.wait_for_load_state("networkidle")

                    target_link = None
                    rows = await geo_page.query_selector_all("tr")
                    anos_prioridade = ["2026", "2025"]
                    
                    for ano in anos_prioridade:
                        for row in rows:
                            row_text = await row.inner_text()
                            if f"/{ano}" in row_text: 
                                el_link = await row.query_selector("a[title='Visualizar Boleto']")
                                if not el_link:
                                        el_link = await row.query_selector("a[href^='javascript:openWindowScrollable']")
                                
                                if el_link:
                                    raw_href = await el_link.get_attribute('href')
                                    match = re.search(r"openWindowScrollable\('([^']+)'", raw_href)
                                    if match:
                                        target_link = match.group(1)
                                        break
                        if target_link:
                            break
                    
                    if not target_link:
                            # Fallback
                            element = await geo_page.query_selector("a[title='Visualizar Boleto']")
                            if not element:
                                element = await geo_page.query_selector("a[href^='javascript:openWindowScrollable']")

                            if element:
                                raw = await element.get_attribute('href')
                                match = re.search(r"openWindowScrollable\('([^']+)'", raw)
                                if match:
                                    target_link = match.group(1)

                    potential_links = [target_link] if target_link else []
                    
                    for link_relative in potential_links:
                        try:
                            popup_url_boleto = f"https://scimpmgsp.geometrus.com.br{link_relative}"
                            await geo_page.goto(popup_url_boleto)
                            await geo_page.wait_for_load_state("networkidle")
                            
                            boleto_text = await geo_page.inner_text('body')
                            
                            ano_match = re.search(r'Exercício:\s*(\d{4})', boleto_text)
                            ano = int(ano_match.group(1)) if ano_match else 0
                            
                            dados_temp = {'ano': ano}
                            match_dados = re.search(r'Pagador\s*\n\s*(.+?)\s*-\s*(CPF|CNPJ):\s*([\d\.\-\/]+)', boleto_text, re.MULTILINE)
                            
                            if match_dados:
                                dados_temp['nome'] = match_dados.group(1).strip()
                                dados_temp['doc_tipo'] = match_dados.group(2)
                                dados_temp['cpf_cnpj'] = match_dados.group(3)
                                dados_temp['tem_cpf'] = True
                            else:
                                    match_nome_only = re.search(r'Pagador\s*\n\s*(.+?)\s*\n', boleto_text, re.MULTILINE)
                                    if match_nome_only:
                                        dados_temp['nome'] = match_nome_only.group(1).strip()
                                        dados_temp['cpf_cnpj'] = None
                                        dados_temp['tem_cpf'] = False
                                        dados_temp['doc_tipo'] = None
                                    else:
                                        continue 
                            
                            # Selection Logic
                            if melhor_candidato is None:
                                melhor_candidato = dados_temp
                            elif ano > melhor_candidato['ano']:
                                melhor_candidato = dados_temp
                            elif ano == melhor_candidato['ano'] and dados_temp['tem_cpf'] and not melhor_candidato['tem_cpf']:
                                    melhor_candidato = dados_temp
                                        
                        except Exception as e:
                            print(f"Falha ao ler boleto {link_relative}: {e}")
                
                if melhor_candidato:
                    result["nome_proprietario"] = melhor_candidato['nome']
                    result["cpf_cnpj"] = melhor_candidato['cpf_cnpj']
                    result["status_processamento"] = "sucesso" if melhor_candidato['tem_cpf'] else "sucesso_parcial"
                    doc_lbl = melhor_candidato.get('doc_tipo') or 'Doc'
                    doc_val = melhor_candidato.get('cpf_cnpj') or 'N/A'
                    print(f"*** [{inscricao_target}] VENCEDOR (Ano {melhor_candidato['ano']}) *** -> {result['nome_proprietario']} | {doc_lbl}: {doc_val}")
                else:
                    if result.get("nome_proprietario"):
                            result["status_processamento"] = "sucesso_certidao_sem_boleto"
                            print(f"*** [{inscricao_target}] Sem boleto, mas com certidão. Proprietário: {result['nome_proprietario']}")
                    elif result.get("valor_venal") or result.get("valor_venal_edificado") or result.get("status_processamento") == "anulada":
                        # If we have value OR it was already marked anulada (by no records), keep/set accordingly
                        if result.get("status_processamento") != "anulada":
                            result["status_processamento"] = "sem_boleto"
                    else:
                        # No Name, No Boleto, No Value -> Anulada
                        result["status_processamento"] = "anulada"
                        print(f"[{inscricao_target}] Sem dados (Nome/Boleto/Valor). Marcando como ANULADA.")

            except Exception as e:
                print(f"Erro ao processar lote {inscricao_target}: {e}")
                result["status_processamento"] = f"erro: {str(e)}"
            
            return result
        
        # --- MAIN LOOP ---
        for i, lote_obj in enumerate(lotes_para_processar):
            
            # --- IP ROTATION CHECK ---
            time_since_rotation = time.time() - last_rotation_time
            if time_since_rotation > 600.0: # Rotate every 10 minutes
                 print(f"⏰ >600s ({time_since_rotation:.1f}s) since last rotation. Rotating now...")
                 await rotate_browser_session()

            # Prepare Inscription
            try:
                zona = str(int(lote_obj['zona']))
            except: zona = str(lote_obj['zona'])
            setor = str(lote_obj['setor']).zfill(4)
            lote_geo = str(lote_obj['loteGeo']).zfill(3)
            inscricao = f"{zona}{setor}{lote_geo}000"
            display_name = f"Quadra {lote_obj.get('quadra')} Lote {lote_obj.get('lote')}"

            if inscricao in lotes_processados_ids:
                if i % 100 == 0: print(f"Skipping {i}...")
                continue
            
            print(f"\nProcessing [{i+1}/{len(lotes_para_processar)}]: {display_name} ({inscricao})")

            # --- RETRY LOOP ---
            max_retries = int(os.getenv("MAX_RETRIES", 20))
            final_result = None
            
            # [NEW] 5-Hour Persistence Loop
            while True:
                for attempt in range(max_retries):
                    if attempt > 0:
                        print(f"⚠️ Retry {attempt+1}/{max_retries} for {inscricao} (Forced Rotation)")
                        
                        # Backoff Strategy
                        wait_time = random.uniform(5, 15) # Default jitter
                        
                        # [NEW] Dynamic Progressive Backoff
                        # Trigger at 50% of attempts remaining (e.g. at 10 if total 20)
                        trigger_point = int(max_retries / 2)
                        
                        if attempt == trigger_point: 
                            print(f"🛑 CRITICAL: {attempt} Errors (50% mark). Initiating 2-HOUR COOL-DOWN...")
                            wait_time = 3600 # 2 Hours
                        elif attempt > trigger_point:
                            print(f"🛑 PERSISTENT ERROR: Wait extended by 1 HOUR...")
                            wait_time = 1200 # 1 Hour

                        print(f"  > Waiting {wait_time:.1f}s before rotating...")
                        await asyncio.sleep(wait_time)
                        
                        await rotate_browser_session() # Force rotation on error retry!
                    
                    res = await process_inscription(inscricao, display_name, page)
                    
                    if "erro" in res["status_processamento"].lower():
                        # If error, try again loop
                        continue
                    else:
                        final_result = res
                        break
                
                if final_result:
                    break
                else:
                    # MAX RETRIES EXHAUSTED
                    print(f"❌ ALL {max_retries} ATTEMPTS FAILED for {inscricao}.")
                    print("🛑 FATAL: Entering 5-HOUR RECOVERY SLEEP before restarting this lot...")
                    print("This mechanism ensures we never skip a lot due to prolonged downtime.")
                    await asyncio.sleep(7200) # 5 Hours
                    # Loop restarts -> attempt reset to 0
                    print("🔄 RESTARTING LOT PROCESSING...")
                    
            
            # if not final_result: # This is unreachable now due to infinite loop above unless break
            #     final_result = res
            
            dados_extraidos.append(final_result)
            lotes_processados_ids.add(inscricao)
            status_main = final_result["status_processamento"]

            # Sub-Units
            # User Request: Don't scan subs if main is 'anulada' (no record found)
            # Sub-Units
            # User Request: Don't scan subs if main is 'anulada' (no record found) -- UPDATED: Scan even if anulada to be sure
            # Strict Anulada Logic: Anulada ONLY if main+subs fail AND no errors.
            # CRITICAL FIX: If main failed due to Network Error ("erro"), DO NOT scan subs. It must be retried as main.
            # GAP FILL: If 'more_subunits' is checked, allow scanning even if it is already 'sucesso_desmembrado'
            should_scan_subs = (status_main in ["sem_boleto", "anulada"] and "erro" not in status_main.lower()) or \
                               (status_main == "sucesso_desmembrado" and reprocess_more_subunits)
            
            if should_scan_subs:
                print(f"  > Inscrição BASE {inscricao} ({status_main}). Iniciando varredura de SUB-UNIDADES...")
                
                # --- SMART PROBE & FILL STRATEGY ---
                sub_idx = 1
                consecutive_misses = 0
                max_consecutive_misses = int(os.getenv("MAX_SCAN_MISSES", 3))
                
                # If we are in "Probe Mode", we jump ahead to check existence
                probe_mode = False 
                probe_step = int(os.getenv("PROBE_STEP", 3))
                
                # Keep track of confirmed ranges to backfill
                backfill_queue = [] 
                
                failed_subs_count_total = 0 # Safety brake
                sub_found_count = 0 # Initialize counter
                
                # [Gap Fill] Calculate Max Known Subunit
                max_known_sub = 0
                if reprocess_more_subunits:
                    base_prefix = inscricao[:-3]
                    for known_id in lotes_processados_ids:
                         # Check if belongs to same base
                         if known_id.startswith(base_prefix) and len(known_id) == len(inscricao) and known_id != inscricao:
                             try:
                                 s_num = int(known_id[-3:])
                                 if s_num > max_known_sub: max_known_sub = s_num
                             except: pass
                    if max_known_sub > 0:
                        print(f"    [Gap Fill] Max Subunidade Conhecida: {max_known_sub}. Forçando varredura de lacunas até lá.")
                
                while True:
                    # Determine next sub to check
                    if backfill_queue:
                         current_sub = backfill_queue.pop(0)
                         is_probe = False
                    else:
                        # [Gap Fill] Reset misses if forced
                        if reprocess_more_subunits and consecutive_misses > 0 and sub_idx < max_known_sub:
                             print(f"      [Gap Fill] Ignorando limites de miss ({consecutive_misses}) pois alvo {sub_idx} <= Max {max_known_sub}...")
                             consecutive_misses = 0

                        if consecutive_misses >= max_consecutive_misses:
                             # Switch to PROBE MODE or STOP
                             if not probe_mode:
                                 print(f"      -> {consecutive_misses} misses. Switching to PROBE MODE (Step +{probe_step})...")
                                 probe_mode = True
                                 # Jump ahead
                                 sub_idx += probe_step 
                             else:
                                 # We were already probing and missed again?
                                 # If we miss IN PROBE MODE, it likely means the building ended.
                                 # Logic: If we probe 015 (miss), then 018 (miss)... maybe try one more?
                                 if consecutive_misses >= max_consecutive_misses + 1: # Give it 1 extra slack in probe
                                     print("      -> Probe failed repeatedly. Stopping sub-unit scan.")
                                     break
                                 sub_idx += probe_step
                        else:
                             # Normal sequential increment
                             # If we just finished a backfill, resume from max known
                             pass # sub_idx is already incremented at end of loop
                        
                        current_sub = sub_idx
                        is_probe = probe_mode

                    if current_sub > 999: break # Safety limit

                    sub_lote = str(current_sub).zfill(3)
                    inscricao_sub = f"{inscricao[:-3]}{sub_lote}" # Remove last 3 "000" and replace
                    
                    # Skip if already processed (unless updating)
                    if inscricao_sub in lotes_processados_ids and not update_mode:
                        print(f"      [Sub {sub_lote}] Já processado. Pulando.")
                        if not backfill_queue: sub_idx = current_sub + 1
                        continue

                    print(f"    > Verificando Sub-unidade: {inscricao_sub} (Probe: {is_probe})")
                    

                    # --- Sub-unit Inscription Logic with Retries ---
                    is_valid_sub = False
                    max_sub_retries = int(os.getenv("MAX_SUB_RETRIES", 3))
                    
                    for sub_attempt in range(max_sub_retries):
                        if sub_attempt > 0:
                            print(f"      ⚠️ Retry {sub_attempt}/{max_sub_retries} for Sub {sub_lote}...")
                            
                            # [NEW] Progressive Backoff for Sub-units
                            wait_time = random.uniform(2, 5)
                            trigger_point = int(max_sub_retries / 2)
                            
                            if sub_attempt == trigger_point: 
                                print(f"🛑 CRITICAL (Sub): {sub_attempt} Errors. Initiating 2-HOUR COOL-DOWN...")
                                wait_time = 3600 
                            elif sub_attempt > trigger_point:
                                print(f"🛑 PERSISTENT ERROR (Sub): Wait extended by 1 HOUR...")
                                wait_time = 1800
                            
                            print(f"      > Waiting {wait_time:.1f}s...")
                            await asyncio.sleep(wait_time) 
                        
                        sub_res = await process_inscription(inscricao_sub, f"{display_name} - Sub {sub_lote}", page)
                        
                        if "erro" in sub_res["status_processamento"].lower():
                            print(f"      [Sub {sub_lote}] Erro de conexão/captcha (Tentativa {sub_attempt+1}).")
                            if sub_attempt == max_sub_retries - 1:
                                # Last attempt failed
                                pass 
                            else:
                                continue # Retry
                        
                        # If we are here, we either succeeded or got a definitive "Anulada/Non-existent"
                        # For "anulada", we don't retry.
                        
                        is_valid_sub = sub_res["status_processamento"] not in ["anulada", "erro_generico"] 
                        if sub_res.get("status_processamento") == "anulada":
                            is_valid_sub = False
                            
                        # If success or explicit fail (anulada), break retry loop
                        # If error, we continued above.
                        break
                    
                    if is_valid_sub:
                        print(f"      ✅ [Sub {sub_lote}] ENCONTRADA! ({sub_res['status_processamento']})")
                        dados_extraidos.append(sub_res)
                        lotes_processados_ids.add(inscricao_sub)
                        atomic_write_json(dados_extraidos, output_file)
                        
                        sub_found_count += 1
                        consecutive_misses = 0 # Reset misses
                        
                        if is_probe:
                            print(f"      🎯 Probe HT! Found {sub_lote}. Backfilling gap...")
                            # Backfill logic: We jumped from (current_sub - probe_step) to current_sub.
                            # We should check the ones in between.
                            # Example: Last Checked 002. Missed 003, 004, 005. Probe hit 008.
                            # Wait, my logic for probe trigger is "consecutive misses".
                            # If I was at 002. Tested 003(miss), 004(miss), 005(miss).
                            # Switched to probe. Next is 005 + 3 = 008.
                            # If 008 exists -> Backfill 006, 007. 
                            # (003, 004, 005 were already checked and missed).
                            
                            start_backfill = sub_idx - probe_step + 1
                            end_backfill = current_sub
                            
                            # Range 006 to 007
                            for bf_idx in range(start_backfill, end_backfill):
                                if bf_idx > 0:
                                     backfill_queue.append(bf_idx)
                            
                            # Exit probe mode, resume sequential from here
                            probe_mode = False
                            # Next sequential will be current_sub + 1
                        
                    else:
                        status_final = sub_res.get("status_processamento", "unknown")
                        if "erro" in status_final:
                             print(f"      ❌ [Sub {sub_lote}] Erro após {max_sub_retries} tentativas. Contando como miss.")
                        else:
                             print(f"      ❌ [Sub {sub_lote}] Inexistente/Anulada.")
                        consecutive_misses += 1
                        
                    # Increment for next iteration (unless we are draining backfill queue)
                    if not backfill_queue:
                        if not probe_mode:
                            sub_idx += 1
                        else:
                            # In probe mode, we increment at start of loop logic or handle it there
                            pass 
                        
                    # Handle visual updates or sleeps
                    # Handle visual updates or sleeps
                    
                    # --- IP ROTATION CHECK (Inside Sub-Unit Loop) ---
                    time_since_rotation = time.time() - last_rotation_time
                    if time_since_rotation > 600.0:
                         print(f"⏰ >600s ({time_since_rotation:.1f}s) since last rotation. Rotating inside sub-unit loop...")
                         await rotate_browser_session()

                    await asyncio.sleep(0.5)
                
                # After loop
                if sub_found_count > 0:
                    status_main = "sucesso_desmembrado"
                    # Update main record
                    if final_result: 
                        final_result["status_processamento"] = status_main
                        # Update in list? It's already appended. 
                        # We might need to rewrite the LAST item in dados_extraidos if it was the main lot
                        dados_extraidos[-1] = final_result 
                        atomic_write_json(dados_extraidos, output_file)
                
            # Sleep between lots
            await asyncio.sleep(1)

            # Filter: Only save finalized items (success, anulada, sem_boleto) to JSON
            # Errors stay in memory/logs but are not persisted to 'saida_imoveis_partX.json'
            # to keep the output clean for Legacy consolidation.
            valid_statuses_to_save = ["sucesso", "sucesso_parcial", "sem_boleto", "sucesso_certidao_apenas", "sucesso_desmembrado", "sucesso_certidao_sem_boleto", "anulada"]
            clean_data_to_save = [d for d in dados_extraidos if any(s in d.get('status_processamento', '').lower() for s in valid_statuses_to_save)]
            
            atomic_write_json(clean_data_to_save, output_file)
            print(f"Dados salvos em {output_file} ({len(clean_data_to_save)} items limpos)")

        print(f"\nProcessamento concluído. Dados finais em {output_file}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())

