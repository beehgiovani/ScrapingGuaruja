import os
import signal
import subprocess
import json
import sys
import shutil
import random
import time
from enum import Enum
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from data_normalizer import normalize_lot_data, is_valid_lot

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global process variable
current_process: Optional[subprocess.Popen] = None
LOG_FILE = "execution.log"
INPUT_FILE = "entrada_lotes.json"
OUTPUT_FILE = "saida_imoveis.json"

# Global Configuration
SERVER_CONFIG = {
    "target_zones": ["0", "1", "2", "3", "4", "5", "6"], # Default all
    "connection_mode": "PROXY", # PROXY, TOR, DIRECT
    "num_workers": 20,
    # Advanced Configuration Defaults
    "headless": True,
    "timeout_ms": 90000,
    "max_retries": 20,
    "captcha_attempts": 15,
    "max_scan_misses": 3,
    "probe_step": 3,
    "max_sub_retries": 3
}

class ProcessStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"

class Stats(BaseModel):
    total: int
    processed: int
    valid_success: int
    errors: int
    status: ProcessStatus



# Helper to prevent caching
def no_cache_response(data):
    from fastapi.responses import JSONResponse
    return JSONResponse(content=data, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", 
        "Pragma": "no-cache", 
        "Expires": "0"
    })

@app.get("/api/status")
def get_status():
    global current_process
    is_running = current_process is not None and current_process.poll() is None
    
    # Check if run_parallel processes are running (simple check)
    if not is_running:
        try:
            # WINDOWS: Use tasklist to check if script is running
            # This is a loose check, but better than crashing
            res = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe"], capture_output=True, text=True)
            if "python.exe" in res.stdout:
                 # Ideally we'd check command line args, but standard tasklist doesn't show them easily without /v /fo csv etc
                 # For now, if current_process is None, we assume stopped unless we find a robust way.
                 # Let's trust internal state more, or check if 'python' is running might be too broad.
                 pass
        except: pass

    
    # 0. Global Aggregates
    total = 0
    total_processed = 0
    total_success = 0
    total_errors = 0
    workers = []

    # 1. Analyze files for stats (Input Total)
    input_set = set()
    if os.path.exists(INPUT_FILE):
        try:
            with open(INPUT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                valid_lotes = []
                # Support both dict and list
                raw_lotes = []
                if isinstance(data, dict) and 'data' in data:
                    raw_lotes = list(data['data'].values())
                elif isinstance(data, list):
                    raw_lotes = data
                
                for l in raw_lotes:
                    if is_valid_lot(l):
                         valid_lotes.append(l)
                         # Collect ID for intersection check
                         try:
                            norm = normalize_lot_data(l)
                            if norm['zona'] and norm['setor'] and norm['loteGeo']:
                                 z = str(int(norm['zona']))
                                 s = str(norm['setor']).zfill(4)
                                 g = str(norm['loteGeo']).zfill(3)
                                 base_id = f"{z}{s}{g}000"
                                 input_set.add(base_id)
                         except: pass

                total = len(valid_lotes)
                # Ensure input_set matches total (approx)
                # total = len(input_set) 
        except:
            pass
            
    # 2. Iterate Output Files + Log Files to discover ALL workers
    import glob
    import re
    
    # Collect all known Worker IDs (integers) and Legacy/Files
    worker_map = {} # id (int) -> string name
    
    # scan logs (Main source for active workers)
    log_files = glob.glob("worker_*.log")
    for lf in log_files:
        try:
            # worker_0.log
            idx = int(re.search(r"worker_(\d+)", lf).group(1))
            worker_map[idx] = {"name": f"Worker {idx}", "json": f"saida_imoveis_part{idx}.json"}
        except: pass
        
    # scan existing outputs (source for finished/legacy stats)
    json_files = glob.glob("saida_imoveis*.json")
    json_files.sort()
    
    processed_base_ids = set()
    
    def get_base(insc):
        if len(insc) == 11:
            return insc[:8] + "000"
        return insc

    # Merge legacy
    legacy_items = []
    
    for out_f in json_files:
        # Determine if this belongs to a known worker or is legacy
        is_worker = False
        if "_part" in out_f:
             try:
                 idx = int(out_f.split('_part')[1].replace('.json', ''))
                 if idx not in worker_map:
                     worker_map[idx] = {"name": f"Worker {idx}", "json": out_f}
                 is_worker = True
             except: pass
        
        if not is_worker and out_f == "saida_imoveis.json":
             legacy_items.append(out_f)

    # Now iterate all known workers (sorted)
    sorted_ids = sorted(worker_map.keys())
    
    # Process "Legacy" first if exists
    for leg_f in legacy_items:
        w_processed = 0
        w_success = 0
        w_errors = 0
        try:
            with open(leg_f, 'r', encoding='utf-8') as f:
                out_data = json.load(f)
                w_processed = len(out_data)
                for item in out_data:
                    status = item.get('status_processamento', '')
                    if 'sucesso' in status: w_success += 1
                    elif 'erro' in status or 'sem_boleto' in status: w_errors += 1
                    if item.get('inscricao'): processed_base_ids.add(get_base(item['inscricao']))
        except: pass
        
        total_processed += w_processed
        total_success += w_success
        total_errors += w_errors
        workers.append({"name": "Legacy/Main", "processed": w_processed, "success": w_success, "errors": w_errors})

    # Process Workers
    for idx in sorted_ids:
        info = worker_map[idx]
        w_processed = 0
        w_success = 0
        w_errors = 0
        
        if os.path.exists(info['json']):
            try:
                with open(info['json'], 'r', encoding='utf-8') as f:
                    out_data = json.load(f)
                    w_processed = len(out_data)
                    for item in out_data:
                        status = item.get('status_processamento', '')
                        if 'sucesso' in status: w_success += 1
                        elif 'erro' in status or 'sem_boleto' in status: w_errors += 1
                        if item.get('inscricao'): processed_base_ids.add(get_base(item['inscricao']))
            except: pass
            
        total_processed += w_processed
        total_success += w_success
        total_errors += w_errors
        
        workers.append({
            "name": info['name'],
            "processed": w_processed,
            "success": w_success,
            "errors": w_errors
        })
    
    # 3. Calculate Missing Inputs
    # We only count as "processed input" if the base ID (000) was touched.
    # Logic: intersection of input_set and processed_base_ids
    processed_inputs = len(input_set.intersection(processed_base_ids))
    missing_inputs = len(input_set) - processed_inputs
    if missing_inputs < 0: missing_inputs = 0

    return no_cache_response({
        "status": "running" if is_running else "stopped",
        "total": total,
        "processed": total_processed, # Total output items (lines)
        "processed_inputs": processed_inputs, # Unique base lots done
        "missing_inputs": missing_inputs, # Missing base lots
        "success": total_success,
        "errors": total_errors,
        "workers": workers
    })

@app.get("/api/data")
def get_data():
    import glob
    unique_map = {}
    
    # 1. Load Legacy (Oldest Source)
    legacy_file = "saida_imoveis.json"
    if os.path.exists(legacy_file):
        try:
            with open(legacy_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if item.get('inscricao'):
                            unique_map[item['inscricao']] = item
        except: pass

    # 2. Load Shards (Newest Source) - Overwrites Legacy
    output_files = sorted(glob.glob("saida_imoveis_part*.json"))
    for out_f in output_files:
        try:
            with open(out_f, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if item.get('inscricao'):
                            unique_map[item['inscricao']] = item
        except: pass
            
    return no_cache_response(list(unique_map.values()))

def remove_errors_from_files():
    """Removes non-success items from all output files to clear 'Errors' from UI"""
    import glob
    files = glob.glob("saida_imoveis*.json")
    removed_total = 0
    
    for fpath in files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, list): continue
            
            # Keep only Successes (and parciais depending on definition, but user wants to re-check 'sem_boleto' etc)
            # Actually, standard SMART_RESUME skips 'sucesso' and 'sucesso_parcial'.
            # So we should KEEP those.
            # We REMOVE 'erro', 'sem_boleto'.
            
            new_data = [item for item in data if item.get('status_processamento') in ['sucesso', 'sucesso_parcial', 'sucesso_certidao_apenas', 'sucesso_desmembrado', 'sucesso_certidao_sem_boleto']]
            
            if len(new_data) < len(data):
                removed_total += (len(data) - len(new_data))
                with open(fpath, 'w', encoding='utf-8') as f:
                    json.dump(new_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Error sanitizing {fpath}: {e}")
            
    print(f"Sanitized files. Removed {removed_total} error records.")

@app.post("/api/start")
def start_process(mode: str = "SMART_RESUME", conn_mode: str = "PROXY", reprocess: str = None):
    global current_process
    
    # Check if run_parallel is running via pgrep to be sure
    # Check if run_parallel is running via tasklist (simplification)
    # res = subprocess.run(["pgrep", "-f", "run_parallel.py"], capture_output=True)
    # if res.returncode == 0:
    #      return {"status": "error", "message": "Processo (run_parallel) já está em execução"}
    
    # In Windows, checking specifically for "run_parallel.py" via tasklist is hard without WMI.
    # We will rely on the global variable 'current_process' for now to avoid complexity or false negatives.
    pass

    if current_process is not None and current_process.poll() is None:
        return {"status": "error", "message": "Processo já está em execução (via server)"}
    
    # SANITIZATION STEP
    if mode == "SMART_RESUME":
        remove_errors_from_files()

    # Open log file
    log_file = open(LOG_FILE, "w", encoding="utf-8")
    
    # Prepare environment variables
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["EXECUTION_MODE"] = mode
    if reprocess: env["REPROCESS_FLAGS"] = reprocess
    
    # Set Connection Mode
    if conn_mode == "TOR":
        env["USE_TOR"] = "true"
        env["USE_PROXY"] = "false"
    elif conn_mode == "DIRECT":
        env["USE_TOR"] = "false"
        env["USE_PROXY"] = "false"
    else: # Default: PROXY
        env["USE_TOR"] = "false"
        env["USE_PROXY"] = "true"

    # Inject Filter & Proxy Config
    env["TARGET_ZONES"] = ",".join(SERVER_CONFIG["target_zones"])

    # Inject Advanced Configuration
    env["HEADLESS_MODE"] = str(SERVER_CONFIG.get("headless", True)).lower()
    env["DEFAULT_TIMEOUT"] = str(SERVER_CONFIG.get("timeout_ms", 90000))
    env["MAX_RETRIES"] = str(SERVER_CONFIG.get("max_retries", 20))
    env["CAPTCHA_ATTEMPTS"] = str(SERVER_CONFIG.get("captcha_attempts", 15))
    env["MAX_SCAN_MISSES"] = str(SERVER_CONFIG.get("max_scan_misses", 3))
    env["PROBE_STEP"] = str(SERVER_CONFIG.get("probe_step", 3))
    env["MAX_SUB_RETRIES"] = str(SERVER_CONFIG.get("max_sub_retries", 3))
    
    # Connection Mode Logic
    conn_mode = SERVER_CONFIG.get("connection_mode", "PROXY")
    if conn_mode == "TOR":
        env["USE_TOR"] = "true"
        env["USE_PROXY"] = "false" # Legacy check
        env["USE_PROXY_GLOBAL"] = "false"
    elif conn_mode == "DIRECT":
        env["USE_TOR"] = "false"
        env["USE_PROXY"] = "false"
        env["USE_PROXY_GLOBAL"] = "false"
    else: # PROXY
         env["USE_TOR"] = "false"
         env["USE_PROXY"] = "true"
         env["USE_PROXY_GLOBAL"] = "true"

    # Start subprocess (RUN PARALLEL)
    # Start subprocess (RUN PARALLEL)
    try:
        # [NEW] Ensure clean slate for Tor and Python
        try:
            subprocess.run(["taskkill", "/F", "/IM", "tor.exe"], capture_output=True)
            # subprocess.run(["taskkill", "/F", "/IM", "python.exe"], capture_output=True) # REMOVED: Kills server itself!
        except: pass

        num_workers = int(SERVER_CONFIG.get("num_workers", 20))
        # Start run_parallel.py with configured workers
        current_process = subprocess.Popen(
            [sys.executable, "-u", "run_parallel.py", "--workers", str(num_workers)], 
            stdout=log_file,  
            stderr=subprocess.STDOUT, 
            text=True, 
            cwd=os.getcwd(),
            env=env
        )
        return {"status": "success", "message": f"Processo Paralelo iniciado em modo {mode}", "pid": current_process.pid}
    except Exception as e:
        log_file.close()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stop")
def stop_process():
    global current_process
    
    if current_process:
        pid = current_process.pid
        print(f"🛑 Killing process tree for PID {pid}...")
        # Use taskkill /T (Tree) /F (Force) /PID 
        try:
             subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        except Exception as e:
             print(f"Error killing process: {e}")

        # Ensure python object is updated
        current_process = None
    
    # [NEW] Wait for handles to release and Consolidate
    print("⏳ Waiting for file handles to release...")
    time.sleep(2)
    
    msg = "Todos os processos foram interrompidos."
    
    try:
        print("🔄 Auto-Consolidating Data...")
        # Import dynamically to ensure we get the function
        from consolidate_output import consolidate_outputs
        consolidate_outputs()
        msg += " Dados foram CONSOLIDADOS no arquivo mestre."
    except Exception as e:
        print(f"❌ Error during auto-consolidation: {e}")
        msg += f" (Erro na consolidação: {e})"

    return {"message": msg}

@app.post("/api/reset")
def reset_data():
    global current_process
    if current_process is not None and current_process.poll() is None:
         raise HTTPException(status_code=400, detail="Cannot reset while process is running. Stop it first.")
    
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)
        
    return {"message": "Data reset successfully"}

@app.get("/api/config")
def get_config():
    return SERVER_CONFIG

@app.post("/api/config")
def update_config(data: dict):
    global SERVER_CONFIG
    SERVER_CONFIG.update(data)
    return {"status": "success", "config": SERVER_CONFIG}

@app.post("/api/proxies/scrape")
def scrape_proxies():
    # Run scraper in background or blocking? Blocking is fine for now (it takes < 30s)
    try:
        # Run proxy_scraper.py
        res = subprocess.run([sys.executable, "proxy_scraper.py"], capture_output=True, text=True)
        if res.returncode == 0:
            # Read the list to return to UI
            proxies = []
            if os.path.exists("proxy_list.txt"):
                with open("proxy_list.txt", "r") as f:
                    proxies = [l.strip() for l in f if l.strip()]
            
            return {
                "status": "success", 
                "message": f"Busca concluída. {len(proxies)} proxies encontrados.", 
                "proxies": proxies
            }
        else:
            return {"status": "error", "message": f"Scraping failed: {res.stderr}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/logs")
def get_logs(source: str = "all"):
    logs_content = ""
    
    # Helper to safe read
    def read_safe(path, title=None):
        out = ""
        if os.path.exists(path):
            try:
                # Copy to temp file to avoid locking conflicts (Windows)
                temp_path = path + f".tmp_{random.randint(1000,9999)}"
                shutil.copy2(path, temp_path)
                
                with open(temp_path, "r", encoding="utf-8", errors="replace") as f:
                    c = f.read()
                    if c:
                        if title: out += f"=== {title} ===\n"
                        # If filtering specific source, show more history. If all, show less.
                        limit = 10000 if source != "all" else 2000
                        out += c[-limit:] + "\n\n"
                
                # Cleanup
                try: os.remove(temp_path)
                except: pass
                
            except Exception as e:
                 out += f"[Error reading log: {e}]\n"
        return out

    if source == "all" or source == "main":
        logs_content += read_safe(LOG_FILE, "SERVER / MAIN LOG")

    import glob
    worker_files = sorted(glob.glob("worker_*.log"))
    
    for w_file in worker_files:
        name_key = w_file.replace(".log", "").lower() # worker_0
        display_name = name_key.upper() # WORKER_0
        
        # If source is "all", include it
        if source == "all":
            logs_content += read_safe(w_file, display_name)
        # If source matches specific worker key (e.g. worker_0)
        elif source == name_key:
             logs_content += read_safe(w_file, display_name)
        
    if not logs_content:
        return {"logs": "Aguardando logs..."}
        
    return no_cache_response({"logs": logs_content})

@app.get("/api/export_pdf")
def export_pdf(bairro: str = None, rua: str = None, group_by: str = None, columns: str = "inscricao,lote,endereco,proprietario,documento", include_errors: str = "false"):
    from fpdf import FPDF
    import glob
    import json
    import os
    import unicodedata
    from fastapi import Response
    
    print(">>> EXPORT PDF SIMPLIFICADO INICIADO")

    # 1. Helper for encoding safety
    def clean(text):
        if text is None: return ""
        text = str(text)
        # Normalize and keep only ascii
        try:
            text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode('ascii')
        except:
            return "" # Fallback
        return text

    # 2. Load Data
    all_data = []
    output_files = glob.glob("saida_imoveis*.json")
    for out_f in output_files:
        try:
            with open(out_f, 'r', encoding='utf-8') as f:
                d = json.load(f)
                if isinstance(d, list): all_data.extend(d)
        except: pass
    
    if not all_data:
         raise HTTPException(status_code=404, detail="Nenhum dado encontrado nos arquivos")

    # Deduplicate by inscricao
    unique_map = {}
    for item in all_data:
        if item.get('inscricao'):
            unique_map[item['inscricao']] = item
    data = list(unique_map.values())

    # 3. Process Filters
    show_errors = include_errors.lower() == "true"
    if not show_errors:
        data = [i for i in data if 'sucesso' in i.get('status_processamento', '').lower()]

    if bairro:
        data = [i for i in data if bairro.lower() in (i.get('bairro') or '').lower()]
    if rua:
        data = [i for i in data if rua.lower() in (i.get('rua') or i.get('endereco') or '').lower()]

    if not data:
        raise HTTPException(status_code=404, detail="Nenhum dado encontrado após filtros")
        
    # Sort by Inscricao
    data.sort(key=lambda x: x.get('inscricao', ''))

    # === HIERARCHICAL GROUPING: ZONA -> BAIRRO -> RUA -> ITEMS ===
    def extract_zona(inscricao):
        if not inscricao or len(inscricao) < 1: return "DESCONHECIDA"
        # First digit is Zona usually
        return inscricao[0]
    
    # Structure: {zona: {bairro: {rua: [items]}}}
    zona_hierarchy = {}
    for item in data:
        zona = extract_zona(item.get('inscricao', ''))
        bairro_name = (item.get('bairro') or 'SEM BAIRRO').strip().upper()
        # Use endereco or rua as key, fallback to SEM RUA
        rua_key = (item.get('rua') or item.get('endereco') or 'SEM RUA').strip().upper()
        
        if zona not in zona_hierarchy: zona_hierarchy[zona] = {}
        if bairro_name not in zona_hierarchy[zona]: zona_hierarchy[zona][bairro_name] = {}
        if rua_key not in zona_hierarchy[zona][bairro_name]: zona_hierarchy[zona][bairro_name][rua_key] = []
        
        zona_hierarchy[zona][bairro_name][rua_key].append(item)
    
    sorted_zonas = sorted(zona_hierarchy.keys())

    # 4. Define Columns
    # Map UI column names to keys and labels
    col_mapping = {
        'inscricao': {'label': 'Inscricao', 'w': 30, 'key': 'inscricao'},
        'lote': {'label': 'Lote', 'w': 30, 'key': 'nome_lote'},
        'endereco': {'label': 'Endereco', 'w': 60, 'key': 'endereco'}, # Fallback checks 'rua'
        'proprietario': {'label': 'Proprietario', 'w': 50, 'key': 'nome_proprietario'},
        'documento': {'label': 'Doc', 'w': 30, 'key': 'cpf_cnpj'},
        'valor_venal': {'label': 'Valor', 'w': 30, 'key': 'valor_venal'},
        'metragem': {'label': 'Area', 'w': 25, 'key': 'metragem'}, # Changed key to 'metragem'
        'testada': {'label': 'Testada', 'w': 20, 'key': 'testada_principal'}
    }
    
    selected_keys = columns.split(',') if columns else ['inscricao', 'lote', 'endereco', 'proprietario']
    active_cols = []
    
    # Calculate widths to fit page (A4 width ~210mm, margins ~20mm => ~190mm usable)
    total_fixed_width = 0
    for k in selected_keys:
        if k in col_mapping:
            active_cols.append(col_mapping[k])
            total_fixed_width += col_mapping[k]['w']
            
    # Scale if necessary
    scale = 1.0
    if total_fixed_width > 0:
        scale = 275.0 / total_fixed_width  # 275mm usable width for Landscape A4 (297mm total)
    
    # 5. Generate PDF
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    
    # Add logo
    logo_path = 'static/logo_omega.png'
    if os.path.exists(logo_path):
        try:
            pdf.image(logo_path, x=10, y=8, w=40)
        except:
            pass

    # Title
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Relatorio de Imoveis", 0, 1, 'C')
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 6, f"Total: {len(data)} registros", 0, 1, 'C')
    pdf.ln(5)
    
    def print_header():
        # Legend
        pdf.set_font("Arial", "", 8)
        current_x = pdf.get_x()
        current_y = pdf.get_y()
        
        # Draw Legend Box (Darker Blue: 200, 225, 255)
        pdf.set_fill_color(200, 225, 255)
        pdf.rect(current_x, current_y, 4, 4, 'F')
        
        # Legend Text
        pdf.set_xy(current_x + 5, current_y)
        pdf.cell(50, 4, "Lotes Desmembrados / Sub-unidades", 0, 1, 'L')
        pdf.ln(2)
        
        # Column Headers
        pdf.set_font("Arial", "B", 9)
        pdf.set_fill_color(200, 200, 200)
        for col in active_cols:
            w = col['w'] * scale
            pdf.cell(w, 8, col['label'], 1, 0, 'C', True)
        pdf.ln()

    print_header()

    pdf.set_font("Arial", "", 8)
    
    # Process Heirarchy
    for zona in sorted_zonas:
        # Check space for Zona Header
        if pdf.get_y() > 190: pdf.add_page(); print_header()
        
        # Zona Header
        pdf.set_font("Arial", "B", 14)
        pdf.set_fill_color(0, 102, 153) # Blue
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 10, f"ZONA {zona}", 0, 1, 'L', True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)
        
        sorted_bairros = sorted(zona_hierarchy[zona].keys())
        for bairro_name in sorted_bairros:
            ruas_dict = zona_hierarchy[zona][bairro_name]
            
            # Check space for Bairro Header
            if pdf.get_y() > 190: pdf.add_page(); print_header()

            # Bairro Header
            pdf.set_font("Arial", "B", 11)
            pdf.set_fill_color(220, 220, 220) # Gray
            pdf.cell(0, 8, clean(f"BAIRRO: {bairro_name}"), 0, 1, 'L', True)
            pdf.set_font("Arial", "", 8)
            pdf.ln(1)
            
            # Iterate Ruas
            sorted_ruas = sorted(ruas_dict.keys())
            for rua_name in sorted_ruas:
                items = ruas_dict[rua_name]

                # Check space for Rua Header
                if pdf.get_y() > 190: pdf.add_page(); print_header()
                
                # Rua Header
                pdf.set_font("Arial", "B", 9)
                pdf.set_fill_color(240, 248, 255) # ALICE BLUE (Very light blue)
                pdf.cell(0, 6, clean(f"RUA: {rua_name} ({len(items)} registros)"), 1, 1, 'L', True) # Added Border=1 and Fill=True
                pdf.set_font("Arial", "", 8)

                for item in items:
                    # 1. Calculate Max Lines needed for this row
                    max_lines = 1
                    row_data = [] # List of (text, width, lines_needed) needed to print
                    
                    for col in active_cols:
                        w = col['w'] * scale
                        key = col['key']
                        val = item.get(key, '')
                         # Special getters
                        if key == 'endereco':
                            val = item.get('endereco') or item.get('rua', '')
                        elif key == 'metragem':
                            # Key is now 'metragem', so val is correct. Fallback only if empty.
                            if not val: val = item.get('area_terreno', '')
                        
                        text = clean(val)
                        # Estimate lines: text_width / col_width
                        text_width = pdf.get_string_width(text)
                        lines = 1
                        if text_width > w - 2: # Buffer
                            lines = int(text_width / (w - 2)) + 1
                        
                        # Cap at 3 lines
                        if lines > 3: lines = 3
                        
                        if lines > max_lines: max_lines = lines
                        row_data.append((text, w, lines))

                    # 2. Calculate row height
                    line_height = 5
                    row_height = max_lines * line_height

                    # 3. Check Page Break
                    if pdf.get_y() + row_height > 190: 
                        pdf.add_page()
                        print_header()
                        pdf.set_font("Arial", "", 8)
                        
                    # 4. Print Row
                    current_x = pdf.get_x()
                    current_y = pdf.get_y() # Save Top Y
                    
                    for i, (text, w, lines_needed) in enumerate(row_data):
                        # Determine highlight
                        is_highlight = False
                        inscricao = item.get('inscricao', '')
                        # Heuristic: If last 3 chars != '000', treat as sub-unit/subproduct
                        if inscricao and len(inscricao) >= 3:
                            if inscricao[-3:] != '000':
                                is_highlight = True
                        
                        # Use MultiCell for printing text
                        # Draw Border manually (and Fill if highlighted)
                        if is_highlight:
                            # User requested darker blue (200, 225, 255)
                            pdf.set_fill_color(200, 225, 255) 
                            pdf.rect(current_x, current_y, w, row_height, style='FD')
                        else:
                            pdf.rect(current_x, current_y, w, row_height, style='D')
                        
                        # Print Text inside
                        pdf.set_xy(current_x, current_y)
                        
                        pdf.multi_cell(w, line_height, text, border=0, align='L', fill=False)
                        
                        # Move to next column X
                        current_x += w
                        pdf.set_xy(current_x, current_y) # Reset to Top Y for next col

                    # 5. Advance Row
                    pdf.set_y(current_y + row_height)
                # Space after Rua
                pdf.ln(2)

            # Space after Bairro
            pdf.ln(4)
        # Space after Zona
        pdf.ln(6)

    # Output
    try:
        pdf_bytes = pdf.output(dest='S')
        if isinstance(pdf_bytes, str):
            final_bytes = pdf_bytes.encode('latin-1')
        else:
            final_bytes = bytes(pdf_bytes)
            
        return Response(
            content=final_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=relatorio_imoveis_basico.pdf"}
        )
    except Exception as e:
        print(f"CRITICAL ERROR generating PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao gerar PDF: {str(e)}")


@app.get("/api/comparison")
def get_comparison():
    input_lotes = []
    if os.path.exists(INPUT_FILE):
        try:
            with open(INPUT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and 'data' in data:
                    input_lotes = list(data['data'].values())
                elif isinstance(data, list):
                    input_lotes = data
                else: 
                     input_lotes = []
        except: 
            input_lotes = []

    output_data = []
    if os.path.exists(OUTPUT_FILE):
        try:
             with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                 output_data = json.load(f)
        except:
             output_data = []
    
    # Analyze
    input_map = {}
    for l in input_lotes:
        # Use normalizer to extract fields consistently
        normalized = normalize_lot_data(l)
        
        try:
            z = normalized['zona']
            s = normalized['setor']
            g = normalized['loteGeo']
            
            if z and s and g:
                zona_int = int(z)
                zona = str(zona_int)  # "03" -> "3"
                setor = str(s).zfill(4)
                lote_geo = str(g).zfill(3)
                inscricao = f"{zona}{setor}{lote_geo}000"
                
                # Use normalized values for display
                input_map[inscricao] = {
                    "inscricao": inscricao,
                    "quadra": normalized['quadra'],
                    "lote": normalized['lote'],
                    "zona": zona,
                    "setor": setor,
                    "loteGeo": lote_geo
                }
        except:
            continue

    output_ids = set()
    for item in output_data:
        if item.get('inscricao'):
            output_ids.add(item.get('inscricao'))
            
    missing_ids = []
    for insc, info in input_map.items():
        if insc not in output_ids:
            missing_ids.append(info)
            
    # Sort missing by Quadra/Lote if possible
    def sort_key(x):
        try: 
            return (int(x['quadra']), x['lote'])
        except: 
            return (999999, x['lote'])
            
    try:
        missing_ids.sort(key=sort_key)
    except:
        pass
        
    return {
        "total_input": len(input_map),
        "total_output": len(output_ids),
        "total_missing": len(missing_ids),
        "missing_items": missing_ids
    }

# Mount static files LAST to avoid covering API routes
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
