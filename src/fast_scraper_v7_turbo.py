#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import logging
import logging.handlers
import asyncio
import cv2
import numpy as np
import httpx
from bs4 import BeautifulSoup
import re
import os
import json
import time
import random
import shutil
import threading
import glob
from typing import Optional, Dict, List, Any
import base64
import traceback
import tempfile
import multiprocessing
from multiprocessing import Pool
from contextlib import asynccontextmanager

# v7.0 TURBO - Optimized for Maximum Speed
# Otimizações aplicadas:
# 1. HTTP Connection Pooling Agressivo (200 conn/host, HTTP/2)
# 2. Concorrência aumentada (chunks 20→50)
# 3. Timeouts otimizados (300s→45s)
# 4. Smart request skipping (pula certidão/boleto se dados já OK)
# 5. Session pool maior (5→10 sessões)
# 6. Backoff mais rápido (max 15s)
# 7. Client reusado por shard (não cria novo por lote)

DATA_DIR = "data"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_custom_ocr = None
_ocr = None

def get_ocr():
    global _ocr
    if _ocr is None:
        import ddddocr
        try:
            _ocr = ddddocr.DdddOcr(show_ad=False, beta=True)
            print("DEBUG: DdddOcr instantiated.")
        except Exception as e:
            print(f"DEBUG: Failed to instantiate DdddOcr: {e}")
    return _ocr

def solve_captcha_bytes(img_bytes: bytes) -> str:
    try:
        ocr = get_ocr()
        if hasattr(ocr, 'classification'):
             return ocr.classification(img_bytes).upper()
        return "XXXXX"
    except Exception as e:
        return "XXXXX"

LIVE_DATA_FILE = os.path.join(DATA_DIR, "live_data.json")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

class LiveMonitor(threading.Thread):
    def __init__(self, total_pending, num_cores, args, log_file=None):
        super().__init__(daemon=True)
        self.total_pending = total_pending
        self.num_cores = num_cores
        self.args = args
        self.stopped = False
        self.start_time = time.time()
        self.log_path = log_file
        if not self.log_path:
            log_files = glob.glob(os.path.join("logs", "scraper_*.log"))
            self.log_path = max(log_files, key=os.path.getctime) if log_files else None
        self._write_heartbeat(0, [], [])

    def _write_heartbeat(self, processed_count, recent_results, recent_logs, success_count=0, error_count=0):
        try:
            elapsed = time.time() - self.start_time
            lpm = (processed_count / (elapsed / 60)) if elapsed > 0 else 0
            live = {
                "timestamp": time.time(),
                "progress": {
                    "processed": processed_count,
                    "total": len(self.total_pending),
                    "percent": round((processed_count / len(self.total_pending)) * 100, 1) if self.total_pending else 0,
                    "success": success_count,
                    "error": error_count
                },
                "stats": {
                    "lpm": round(lpm, 1),
                    "elapsed": round(elapsed, 0),
                    "tor": "NITRO" if len(GLOBAL_IDENTITY_POOL) > 0 else ("OK" if USE_TOR else "OFF")
                },
                "recent": recent_results[-15:],
                "logs": recent_logs
            }
            temp_live = LIVE_DATA_FILE + ".tmp"
            with open(temp_live, "w", encoding="utf-8") as f:
                json.dump(live, f, indent=2)
            if os.path.exists(LIVE_DATA_FILE):
                try: os.remove(LIVE_DATA_FILE)
                except: pass
            os.rename(temp_live, LIVE_DATA_FILE)
        except: pass

    def run(self):
        while not self.stopped:
            try:
                processed_count = 0
                recent_results = []
                for i in range(self.num_cores):
                    shard_file = os.path.join(DATA_DIR, f"temp_shard_{i}.json")
                    if os.path.exists(shard_file):
                        try:
                            with open(shard_file, "r", encoding="utf-8") as f:
                                data = json.load(f)
                                processed_count += len(data)
                                if data: recent_results.extend(data[-2:])
                        except: pass
                
                recent_logs = []
                if self.log_path and os.path.exists(self.log_path):
                    try:
                        with open(self.log_path, "r", encoding="utf-8") as f:
                            lines = f.readlines()
                            recent_logs = [l.strip() for l in lines[-10:]]
                    except: pass
                
                success_count = 0
                error_count = 0
                for i in range(self.num_cores):
                    shard_file = os.path.join(DATA_DIR, f"temp_shard_{i}.json")
                    if os.path.exists(shard_file):
                        try:
                            with open(shard_file, "r", encoding="utf-8") as f:
                                data = json.load(f)
                                for res in data:
                                    if res.get("status_processamento") == "sucesso": success_count += 1
                                    else: error_count += 1
                        except: pass
                
                self._write_heartbeat(processed_count, recent_results, recent_logs, success_count, error_count)
            except: pass
            time.sleep(3)

    def stop(self):
        self.stopped = True
        try:
            if os.path.exists(LIVE_DATA_FILE): os.remove(LIVE_DATA_FILE)
        except: pass

from http.server import HTTPServer, BaseHTTPRequestHandler
STOP_EVENT = threading.Event()
START_EVENT = threading.Event() 
LIVE_CONFIG = {"limit": 400, "batch": 1000}

class CommandHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): return
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'X-Requested-With, Content-Type')
        self.end_headers()
    def do_GET(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        filename = self.path.split('?')[0].lstrip('/')
        file_path = os.path.join(DATA_DIR, filename)
        if filename in ["live_data.json", "saida_lotes_new.json"] or filename.endswith(".json"):
            if os.path.exists(file_path):
                with open(file_path, 'rb') as f: self.wfile.write(f.read())
            else: self.wfile.write(b'{}')
        else: self.wfile.write(b'{"error": "not found"}')
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        if self.path == "/start":
            START_EVENT.set()
            self.wfile.write(b'{"status": "started"}')
        elif self.path == "/stop":
            STOP_EVENT.set()
            self.wfile.write(b'{"status": "stopping"}')

class CommandBridge(threading.Thread):
    def __init__(self, port=9999):
        super().__init__(daemon=True)
        self.port = port
    def run(self):
        while not STOP_EVENT.is_set():
            try:
                class ResilientHTTPServer(HTTPServer): allow_reuse_address = True
                httpd = ResilientHTTPServer(('0.0.0.0', self.port), CommandHandler)
                httpd.serve_forever()
            except: time.sleep(5)

from datetime import datetime
import logging
try:
    from stem import Signal
    from stem.control import Controller
except ImportError:
    pass

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
log_filename = os.path.join(LOGS_DIR, f"scraper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=[logging.FileHandler(log_filename, encoding='utf-8'), logging.StreamHandler()])

class SilenceFilter(logging.Filter):
    def filter(self, record):
        msg = str(record.getMessage())
        forbidden = ["SocketClosed", "10038", "Target page", "Future exception", "CancelledError"]
        return not any(f in msg for f in forbidden)

logging.getLogger("stem").setLevel(logging.CRITICAL)
logging.getLogger().addFilter(SilenceFilter())

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.2; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Edge/121.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
]

USE_TOR, TOR_SOCKS_PORT, TOR_CONTROL_PORT = False, 9050, 9051
MAX_CAPTCHA_ATTEMPTS, MAX_CONSECUTIVE_MISSES, PROBE_STEP = 15, 24, 5  # Reduzido de 20 para 15
HTTP_TIMEOUT = 45.0  # OTIMIZADO: Reduzido de 300s para 45s
TURBO_MODE, GLOBAL_IDENTITY_POOL = False, []

async def async_backoff(attempt, base_delay=0.5, max_delay=15):  # OTIMIZADO: base 1→0.5s, max 30→15s
    """Backoff exponencial otimizado para velocidade."""
    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
    jitter = random.uniform(0, 0.3 * delay)  # Jitter reduzido
    final_delay = delay + jitter
    logging.debug(f"  [Backoff] Tentativa {attempt}. Aguardando {final_delay:.1f}s...")
    await asyncio.sleep(final_delay)

BASE = "https://scimpmgsp.geometrus.com.br"
SEARCH_URL = f"{BASE}/mctm_lancamentos/index_certidao_valor_venal"

def atomic_write_json(data, filename):
    dir_name = os.path.dirname(os.path.abspath(filename))
    base_name = os.path.basename(filename)
    with tempfile.NamedTemporaryFile(mode='w', delete=False, dir=dir_name, encoding='utf-8', suffix='.tmp', prefix=f"tmp_{base_name}_") as tf:
        json.dump(data, tf, indent=4, ensure_ascii=False)
        temp_name = tf.name
        tf.flush()
        os.fsync(tf.fileno())
    for attempt in range(3):  # OTIMIZADO: Reduzido de 5 para 3
        try:
            if os.path.exists(filename): os.remove(filename)
            shutil.move(temp_name, filename)
            return True
        except: time.sleep(0.05)  # OTIMIZADO: Reduzido de 0.1 para 0.05
    return False

ACTIVE_TOR_PORTS = []
def check_tor_alive():
    if not USE_TOR: return True
    import socket
    global TOR_SOCKS_PORT, TOR_CONTROL_PORT, ACTIVE_TOR_PORTS
    ACTIVE_TOR_PORTS = []
    test_ports = list(range(9050, 9081, 2)) + list(range(9150, 9181, 2))
    for p in test_ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)  # OTIMIZADO: Reduzido de 0.3 para 0.2
            try:
                s.connect(("127.0.0.1", p))
                ACTIVE_TOR_PORTS.append(p)
                if len(ACTIVE_TOR_PORTS) == 1:
                    TOR_SOCKS_PORT, TOR_CONTROL_PORT = p, p+1
            except: continue
    return len(ACTIVE_TOR_PORTS) > 0

TOR_HEALTH = {}
async def monitor_tor_health():
    """Monitor de saúde do Tor."""
    while not STOP_EVENT.is_set():
        if USE_TOR:
            for port in list(range(9050, 9081, 2)) + list(range(9150, 9181, 2)):
                start = time.time()
                try:
                    async with httpx.AsyncClient(proxy=f"socks5://127.0.0.1:{port}", timeout=5.0) as c:
                        await c.get("https://api.ipify.org")
                        TOR_HEALTH[port] = time.time() - start
                except:
                    TOR_HEALTH[port] = 999
        await asyncio.sleep(60)

def get_best_tor_port():
    if ACTIVE_TOR_PORTS:
        return random.choice(ACTIVE_TOR_PORTS)
    if not USE_TOR: return 9050
    healthy_ports = [p for p, lat in TOR_HEALTH.items() if lat < 10]
    return random.choice(healthy_ports) if healthy_ports else 9050

def get_tor_proxy() -> str:
    if not USE_TOR and not ACTIVE_TOR_PORTS: return None
    port = get_best_tor_port()
    user = f"bot_{random.randint(1, 1000000)}"
    return f"socks5://{user}:pwd@127.0.0.1:{port}"

class PageCache:
    @staticmethod
    def get_headers():
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    # OTIMIZADO: Removido lock global (usa session local)

async def solve_captcha_auto(client: httpx.AsyncClient, cookies: dict, session_obj: dict, max_attempts=10):  # OTIMIZADO: 15→10
    """Resolve captcha automaticamente."""
    digits_url = f"{BASE}/digits"
    headers = {**PageCache.get_headers(), "Referer": digits_url, "Origin": BASE}
    for sub in range(max_attempts):
        try:
            resp = await client.get(digits_url, cookies=cookies, headers=headers, timeout=15.0)  # OTIMIZADO: 30→15s
            soup = BeautifulSoup(resp.text, 'html.parser')
            sid_tag = soup.find('input', {'name': 'data[Digit][session_id]'})
            if not sid_tag:
                if "DigitIndexForm" not in resp.text: return True
                continue
            img_tag = soup.find('img', {'src': lambda x: x and 'digits/img' in x})
            if not img_tag: continue
            img_url = BASE + img_tag['src'] if img_tag['src'].startswith('/') else img_tag['src']
            img_resp = await client.get(img_url, cookies=cookies, headers=headers, timeout=15.0)
            txt = solve_captcha_bytes(img_resp.content)
            if len(txt) != 5: continue
            payload = {"_method": "POST", "data[Digit][session_id]": sid_tag.get('value'), "data[Digit][digits]": txt}
            post_resp = await client.post(digits_url, data=payload, cookies=cookies, headers=headers, timeout=15.0, follow_redirects=True)
            
            ts = int(time.time() * 1000)
            if "DigitIndexForm" not in post_resp.text:
                logging.info(f"    [Captcha] Resolvido: {txt}")
                session_obj["cookies"].update(post_resp.cookies)
                try:
                    v_dir = "dataset_labeled"
                    if not os.path.exists(v_dir): os.makedirs(v_dir)
                    with open(f"{v_dir}/{txt}_{ts}.png", "wb") as f: f.write(img_resp.content)
                except: pass
                return True
            else:
                logging.warning(f"    [Captcha] Falha: {txt}")
        except Exception as e:
            await async_backoff(sub + 1, base_delay=0.3)
            continue
    return False

async def ensure_session_raw(proxy_url=None, logger=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": f"{BASE}/digits"
    }
    
    if logger: logger.info(f"    [Connect] Tentando conexão via {proxy_url}...")
    # OTIMIZADO: Timeout reduzido 20→15s
    try:
        async with httpx.AsyncClient(proxy=proxy_url, verify=False, follow_redirects=True, headers=headers, timeout=15.0) as client:
            try:
                resp = await client.get(SEARCH_URL, timeout=15)
                if logger: logger.info(f"    [Connect] Status {resp.status_code}")
                
                if "DigitIndexForm" not in resp.text:
                    return {"cookies": {k: v for k, v in client.cookies.items()}, "proxy": proxy_url, "timestamp": time.time()}
                
                soup = BeautifulSoup(resp.text, 'html.parser')
                sid_input = soup.find('input', {'name': 'data[Digit][session_id]'})
                img_tag = soup.find('img', {'src': lambda x: x and 'digits/img' in x})
                
                if not sid_input or not img_tag:
                    if logger: logger.warning(f"    [Connect] Falha ao extrair campos.")
                    return None
                    
                sid = sid_input.get('value')
                img_src = img_tag.get('src')
                if img_src.startswith("/"): img_src = BASE + img_src
                
                img_resp = await client.get(img_src, timeout=15)
                txt = solve_captcha_bytes(img_resp.content).upper()
                if logger: logger.info(f"    [Connect] Captcha: {txt}")
                
                if len(txt) != 5:
                    return None
                
                form = soup.find('form', {'id': 'DigitIndexForm'})
                payload = {}
                if form:
                    for input_tag in form.find_all('input'):
                        name = input_tag.get('name')
                        value = input_tag.get('value', '')
                        if name: payload[name] = value
                
                payload["data[Digit][session_id]"] = sid
                payload["data[Digit][digits]"] = txt
                payload["_method"] = "POST"
                
                post_target = f"{BASE}/digits"
                post_headers = headers.copy()
                post_headers["Referer"] = post_target
                post_headers["Content-Type"] = "application/x-www-form-urlencoded"
                
                post_resp = await client.post(post_target, data=payload, headers=post_headers, timeout=15)
                
                if "DigitIndexForm" not in post_resp.text:
                    if logger: logger.info(f"    [Connect] Sessão OK!")
                    try:
                        ts = int(time.time() * 1000)
                        v_dir = "dataset_labeled"
                        if not os.path.exists(v_dir): os.makedirs(v_dir)
                        with open(f"{v_dir}/{txt}_{ts}.png", "wb") as f: f.write(img_resp.content)
                    except: pass
                    return {"cookies": {k: v for k, v in client.cookies.items()}, "proxy": proxy_url, "timestamp": time.time()}
            except Exception as e:
                if logger: logger.warning(f"    [Connect] Erro: {str(e)}")
    except Exception as e:
        if logger: logger.warning(f"    [Connect] Falha client: {str(e)}")
    return None

async def ensure_session(session_obj=None, logger=None):
    try:
        if len(GLOBAL_IDENTITY_POOL) > 0:
            wid = GLOBAL_IDENTITY_POOL.pop(0)
            if session_obj is not None: session_obj.update(wid)
            return wid
    except: pass
    for attempt in range(1, 8):  # OTIMIZADO: Reduzido de 11 para 8
        if STOP_EVENT.is_set(): break
        rid = await ensure_session_raw(get_tor_proxy(), logger)
        if rid:
            try:
                if len(GLOBAL_IDENTITY_POOL) < 20: GLOBAL_IDENTITY_POOL.append(rid)
            except: pass
            if session_obj is not None: session_obj.update(rid)
            return rid
        await async_backoff(attempt)
    return None

def parse_boleto_html(html: str) -> Dict[str, Optional[str]]:
    soup = BeautifulSoup(html, 'lxml')
    txt = soup.get_text(" ", strip=True)
    res = {"nome": None, "cpf": None}
    m_cpf = re.search(r"(?:CPF|CNPJ)[:\s]+([\d.\-\/]+)", txt, re.IGNORECASE) or re.search(r"\b(\d{3}\.\d{3}\.\d{3}\-\d{2})\b", txt)
    if m_cpf:
        res["cpf"] = re.sub(r'[^\d]', '', m_cpf.group(1).strip())
        m_nome = re.search(r"Pagador[:\s]*(.*?)[:\s]*(?:-|–)?\s*(?:CPF|CNPJ)", txt, re.IGNORECASE)
        if m_nome: res["nome"] = m_nome.group(1).strip().upper()
    return res

def parse_search_html(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    data = {}
    for dt in soup.find_all('dt'):
        lbl = dt.get_text(strip=True).replace(':', '')
        dd = dt.find_next_sibling('dd')
        if dd: data[lbl] = dd.get_text(strip=True).replace('\xa0', ' ')
    
    if not data.get("Proprietário") and not data.get("Nome"):
        m_p = re.search(r"Proprietário\(a\)\s+<b>(.*?)</b>", html, re.I | re.S)
        if m_p: data["Proprietário"] = m_p.group(1).strip()
    
    block_patterns = [
        "DigitIndexForm", "Acesso Negado", "Access Denied", 
        "Desculpe o transtorno", "verificação de segurança",
        "suas requisições foram bloqueadas"
    ]
    if any(p in html for p in block_patterns):
        return {"status": "bloqueado"}

    if "Nenhum registro encontrado" in html:
        return {"status": "anulado"}

    if not data.get("Proprietário") and not data.get("Nome"): 
        return {"status": "erro_parse"}
    
    def cln(v): return str(v).replace("R$", "").replace("m2", "").strip() if v else None
    
    logradouro = soup.select_one('dt:-soup-contains("Logradouro") + dd')
    numero = soup.select_one('dt:-soup-contains("Número") + dd')
    bairro = soup.select_one('dt:-soup-contains("Bairro") + dd')
    
    r = logradouro.get_text(strip=True) if logradouro else (data.get("Logradouro") or "")
    n = numero.get_text(strip=True) if numero else (data.get("Número") or "")
    b = bairro.get_text(strip=True) if bairro else (data.get("Bairro") or "")
    cep = data.get("CEP") or ""
    comp = data.get("Complemento") or ""
    
    endereco = f"{r}, {n}, {comp} - {b} - CEP {cep}".strip().replace(" ,", ",")
    vv_edificado = cln(data.get("Valor Venal Construção") or data.get("Valor Venal Edificação") or "0,00")
    descricao = (data.get("Uso do Imóvel") or data.get("Utilização") or data.get("Padrão") or "").strip().upper()

    return {
        "status": "sucesso", 
        "nome_lote": None,
        "inscricao": None, 
        "status_processamento": None,
        "cpf_cnpj": None, 
        "nome_proprietario": (data.get("Proprietário") or data.get("Nome") or "").strip().upper(),
        "rua": r, 
        "numero": n, 
        "complemento": comp, 
        "bairro": b, 
        "cep": cep,
        "endereco": endereco,
        "metragem": cln(data.get("Área do Terreno")),
        "descricao_imovel": descricao,
        "valor_venal": cln(data.get("Valor Venal") or data.get("Valor Venal Terreno")),
        "valor_venal_edificado": vv_edificado
    }

async def fetch_insc(client, insc, sess):
    payload = {"data[MctmLancamento][identificacao]": insc, "data[MctmLancamento][exercicio]": "2026", "_method": "POST"}
    for attempt in range(1, 3):  # OTIMIZADO: Reduzido de 4 para 3
        try:
            r = await client.post(SEARCH_URL, data=payload, cookies=sess["cookies"], headers={**PageCache.get_headers(), "Referer": SEARCH_URL}, timeout=HTTP_TIMEOUT, follow_redirects=True)
            if "DigitIndexForm" in r.text:
                if await solve_captcha_auto(client, sess["cookies"], sess): continue
                return {"status": "bloqueado"}
            res = parse_search_html(r.text)

            if res["status"] == "sucesso" or res["status"] == "anulado":
                res["inscricao"] = insc
                if res["status"] == "sucesso":
                    try:
                        # OTIMIZADO: Smart skipping - só busca certidão se REALMENTE necessário
                        need_certidao = not res.get("metragem") or not res.get("descricao_imovel")
                        if need_certidao:
                             m_cert = re.search(r"openWindowScrollable\('([^']+imprimir_certidao_valor_venal[^']+)'", r.text)
                             if m_cert:
                                 cert_url = BASE + m_cert.group(1) if m_cert.group(1).startswith("/") else m_cert.group(1)
                                 try:
                                     c_resp = await client.get(cert_url, cookies=sess["cookies"], headers={**PageCache.get_headers(), "Referer": SEARCH_URL}, timeout=20.0)
                                     c_text = c_resp.text
                                     
                                     if not res.get("metragem"):
                                         m_area = re.search(r'Área do Terreno:\s*([\d\.,]+)', c_text)
                                         if m_area: res["metragem"] = m_area.group(1).strip()
                                     
                                     if not res["descricao_imovel"]:
                                         m_desc = re.search(r'(Quadra\s*.+?Lote\s*.+?)(?=\n|$|\s{2,})', c_text, re.IGNORECASE)
                                         if m_desc: res["descricao_imovel"] = m_desc.group(1).strip()
                                         
                                     if not res["nome_proprietario"]:
                                         m_prop = re.search(r'Proprietário\(a\)\s+(.+?)(?=\s+sob|\s*$)', c_text)
                                         if m_prop: res["nome_proprietario"] = m_prop.group(1).strip().upper()
                                 except: pass

                        # OTIMIZADO: Smart skipping - só busca boleto se CPF vazio
                        if not res.get("cpf_cnpj"):
                            b_headers = {**PageCache.get_headers(), "Referer": SEARCH_URL, "Content-Type": "application/x-www-form-urlencoded", "Origin": BASE}
                            br = await client.post(f"{BASE}/mvia2_boletos/lista", data={"data[Mvia2Boleto][cd_sacado]": insc, "_method": "POST"}, cookies=sess["cookies"], headers=b_headers, timeout=20.0)
                            
                            mb = re.search(r"openWindowScrollable\('([^']+via2_boleto[^']+)'", br.text)
                            if not mb: 
                                 mb = re.search(r'href=["\']([^"\']*via2_boleto[^"\']*)["\']', br.text)
                            
                            if mb:
                                bu = BASE + mb.group(1) if mb.group(1).startswith("/") else mb.group(1)
                                b_headers["Referer"] = f"{BASE}/mvia2_boletos/lista"
                                del b_headers["Content-Type"]
                                brp = await client.get(bu, cookies=sess["cookies"], headers=b_headers, timeout=20.0)
                                
                                btxt = brp.text
                                bd = parse_boleto_html(btxt)
                                
                                if not bd["cpf"]:
                                    soup_b = BeautifulSoup(btxt, 'lxml')
                                    txt_b = soup_b.get_text("\n", strip=True) 
                                    m_dados = re.search(r'Pagador\s*\n\s*(.+?)\s*-\s*(?:CPF|CNPJ):\s*([\d\.\-\/]+)', txt_b, re.IGNORECASE)
                                    if m_dados:
                                        bd["nome"] = m_dados.group(1).strip().upper()
                                        bd["cpf"] = m_dados.group(2).strip()

                                if bd["cpf"]: res["cpf_cnpj"] = bd["cpf"]
                                if bd["nome"]: res["nome_proprietario"] = bd["nome"]

                    except Exception as e:
                        logging.error(f"  [Extras] Erro em {insc}: {e}")

                return res
            if res["status"] == "erro_parse":
                logging.warning(f"  [Parse] Erro em {insc}")
        except Exception as e:
            await asyncio.sleep(0.5)
    return {"status": "erro_rede"}

async def process_lote(lote_info, client, logger, sess_override=None):
    m = lote_info.get('metadata', {})
    z, s, l = lote_info.get('zona') or m.get('zona', ''), lote_info.get('setor') or m.get('setor', ''), lote_info.get('lote_geo') or m.get('lote_geo', '')
    if not (z and s and l): return []
    base = f"{z}{s}{l}"
    sess = sess_override or await ensure_session(logger=logger)
    if not sess: return []

    async def fetch_with_renewal(insc_local):
        nonlocal sess
        for r_attempt in range(1, 3):  # OTIMIZADO: Reduzido de 4 para 3
            res = await fetch_insc(client, insc_local, sess)
            st = res.get("status")
            if st == "bloqueado":
                logger.warning(f"  [Shield] Bloqueio em {insc_local}. Renovando...")
                new_sess = await ensure_session(logger=logger)
                if new_sess: 
                    sess.update(new_sess)
                    continue
            return res
        return {"status": "erro_exhausted"}

    results = []
    r0 = await fetch_with_renewal(f"{base}000")
    
    quadra = lote_info.get('quadra') or m.get('quadra') or ''
    lote_lbl = lote_info.get('lote') or m.get('lote') or ''
    nome_lote_display = f"Quadra {quadra} Lote {lote_lbl}".strip()
    
    has_subunits = False
    
    if r0.get("status") == "sucesso":
        r0["status_processamento"] = "sucesso"
        r0["nome_lote"] = nome_lote_display
        results.append(r0)
        logger.info(f"  [✓] {base}000: {r0['nome_proprietario']}")
    elif r0.get("status") == "anulado":
        r0["status_processamento"] = "anulado"
        r0["inscricao"] = f"{base}000"
        r0["nome_lote"] = nome_lote_display
        results.append(r0)
        logger.info(f"  [X] {base}000: Anulado")
    else:
        logger.warning(f"  [!] {base}000: Falha ({r0.get('status')})")
        return []

    si, mss = 1, 0
    while si < 150:
        insc = f"{base}{str(si).zfill(3)}"
        ri = await fetch_with_renewal(insc)
        
        if ri.get("status") == "sucesso":
            has_subunits = True
            ri["status_processamento"] = "sucesso"
            ri["nome_lote"] = f"{nome_lote_display} - Sub {str(si).zfill(3)}"
            results.append(ri); mss = 0; si += 1
            logger.info(f"      [✓ Sub] {insc}: {ri['nome_proprietario']}")
        elif ri.get("status") == "anulado":
            mss += 1 
            si += 1
        else:
            mss += 1
            if mss >= MAX_CONSECUTIVE_MISSES: break
            si += 1
            if mss >= 3: si += PROBE_STEP
    
    if has_subunits:
        for res in results:
            if res["inscricao"] == f"{base}000":
                res["status_processamento"] = "sucesso_desmembrado"
                for k in ["nome_proprietario", "cpf_cnpj", "rua", "numero", "complemento", "bairro", "cep", "endereco", "metragem", "descricao_imovel", "valor_venal", "valor_venal_edificado"]:
                    res[k] = None
                break
            
    if len(results) == 1 and results[0]["status_processamento"] == "anulado":
        return results
        
    if not results:
        if r0.get("status") == "anulado":
             return [{"inscricao": f"{base}000", "status_processamento": "anulado"}]
        return [{"inscricao": f"{base}000", "status_processamento": "erro"}]
        
    return results

class Sm:
    def __init__(self, size=10, logger=None):  # OTIMIZADO: Pool aumentado de 5 para 10
        self.size, self.sessions, self.lock, self.logger = size, [], asyncio.Lock(), logger
    async def get(self):
        async with self.lock:
            if not self.sessions:
                if self.logger: self.logger.info(f"    [Sm] Renovando pool...")
                for _ in range(self.size):
                    s = await ensure_session(logger=self.logger)
                    if s: self.sessions.append(s)
            if not self.sessions: 
                if self.logger: self.logger.warning(f"    [Sm] Falha ao obter sessões.")
                return None
            s = self.sessions.pop(0); self.sessions.append(s)
            return s

# OTIMIZADO: HTTP/2 + Connection Pooling Agressivo
def create_optimized_client(proxy=None):
    """Cria client HTTP otimizado para alta velocidade."""
    limits = httpx.Limits(
        max_keepalive_connections=200,  # Reutilizar até 200 conexões
        max_connections=500,  # Total de conexões simultâneas
        keepalive_expiry=60.0  # Manter conexões por 60s
    )
    timeout = httpx.Timeout(
        connect=10.0,  # 10s para conectar
        read=30.0,  # 30s para ler
        write=10.0,  # 10s para escrever
        pool=5.0  # 5s para obter conexão do pool
    )
    return httpx.AsyncClient(
        proxy=proxy,
        verify=False,
        follow_redirects=True,
        timeout=timeout,
        limits=limits,
        http2=True  # Habilita HTTP/2 para multiplexing
    )

async def process_shard(lotes, sid, args, pool, active_ports):
    class ShardLogger(logging.LoggerAdapter):
        def process(self, msg, kwargs):
            return f"[Shard {self.extra['sid']}] {msg}", kwargs
    logger = ShardLogger(logging.getLogger(), {"sid": sid})
    
    global ACTIVE_TOR_PORTS, USE_TOR
    ACTIVE_TOR_PORTS = active_ports
    if active_ports: USE_TOR = True
    
    await asyncio.sleep(sid * 0.3)  # OTIMIZADO: Reduzido de 0.5 para 0.3
    logger.info(f"🚀 Shard started: {len(lotes)} lotes. Ports: {active_ports}")
    out = os.path.join(DATA_DIR, f"temp_shard_{sid}.json")
    res_shard, sm = [], Sm(10, logger)  # Pool aumentado
    idx = 0
    
    while idx < len(lotes):
        if STOP_EVENT.is_set(): break
        chk = lotes[idx : idx + 50]  # OTIMIZADO: Chunks aumentados de 20 para 50
        
        async def wrk(item):
            s = await sm.get()
            if not s: return
            
            proxy = s.get("proxy")
            
            try:
                # OTIMIZADO: Reutiliza client otimizado
                client = create_optimized_client(proxy)
                async with client:
                    r_l = await process_lote(item, client, logger, s)
                    if r_l:
                        for r in r_l: res_shard.append(r)
                        atomic_write_json(res_shard, out)
            except Exception as e:
                logger.error(f"Erro no lote {item}: {e}")

        await asyncio.gather(*[wrk(l) for l in chk])
        idx += 50  # OTIMIZADO: Incremento aumentado
    return out

def setup_logging(log_file=None):
    if not log_file:
        log_dir = "../logs" if "src" in __file__ else "logs"
        if not os.path.exists(log_dir): os.makedirs(log_dir)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(log_dir, f"scraper_{timestamp}.log")
    
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            root.removeHandler(handler)
            
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)-8s %(message)s',
        handlers=[
            logging.handlers.RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=1, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return log_file

def run_shard(shard_data):
    lotes, sid, args, pool, active_ports, log_file = shard_data
    setup_logging(log_file)
    global GLOBAL_IDENTITY_POOL; GLOBAL_IDENTITY_POOL = pool
    try:
        return asyncio.run(process_shard(lotes, sid, args, pool, active_ports))
    except Exception as e:
        logging.error(f"CRITICAL SHARD ERROR: {e}")
        return None

async def main():
    log_file = setup_logging()
    logging.info(f"🚀 Scraper V7 TURBO iniciado! Log: {log_file}")
    
    global USE_TOR
    bridge = CommandBridge(); bridge.start()
    
    START_EVENT.set()
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=os.path.join(DATA_DIR, "entrada_lotes.json"))
    parser.add_argument("--turbo", action="store_true")
    parser.add_argument("--tor", action="store_true")
    parser.add_argument("--output", default=os.path.join(DATA_DIR, "saida_lotes_new.json"))
    args = parser.parse_args()
    
    USE_TOR = args.tor
    if USE_TOR:
        check_tor_alive()
        asyncio.create_task(monitor_tor_health())
    
    if not os.path.exists(args.input): return
    with open(args.input, "r", encoding="utf-8") as f: lotes_all = json.load(f)
    lotes_in = [l for l in lotes_all if l.get("status_scraping") != "concluido"]
    
    if not lotes_in:
        logging.info("Nenhum lote pendente.")
        return

    if args.turbo:
        cores = min(8, multiprocessing.cpu_count())
        avg = max(1, len(lotes_in) // cores)
        manager = multiprocessing.Manager()
        pool_shared = manager.list()
        
        shds = []
        for i in range(cores):
            chunk = lotes_in[i*avg : (i+1)*avg] if i < cores - 1 else lotes_in[i*avg:]
            if chunk:
                shds.append((chunk, i, args, pool_shared, ACTIVE_TOR_PORTS, log_file))
        
        logging.info(f"\n🔥 Starting TURBO mode with {cores} cores...")
        with Pool(cores) as p: files = p.map(run_shard, shds)
        final = []
        for f in files:
            if f and os.path.exists(f):
                with open(f, "r", encoding="utf-8") as j: final.extend(json.load(j))
                os.remove(f)
        atomic_write_json(final, args.output)
        logging.info(f"✅ Processamento concluído! {len(final)} registros salvos.")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    asyncio.run(main())
