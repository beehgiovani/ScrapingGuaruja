import os
import signal
import subprocess
import json
import sys
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
            
    # 2. Iterate Output Files (Calculate Processed + Worker Stats + Unique Base Ids)
    import glob
    output_files = glob.glob("saida_imoveis*.json")
    output_files.sort()
    
    processed_base_ids = set()
    
    def get_base(insc):
        if len(insc) == 11:
            return insc[:8] + "000"
        return insc

    for out_f in output_files:
        worker_id = "Legacy"
        if "_part" in out_f:
            try:
                worker_id = f"Worker {out_f.split('_part')[1].replace('.json', '')}"
            except:
                worker_id = out_f
        elif out_f == "saida_imoveis.json":
            worker_id = "Legacy/Main"

        w_processed = 0
        w_success = 0
        w_errors = 0
        
        try:
            with open(out_f, 'r', encoding='utf-8') as f:
                out_data = json.load(f)
                w_processed = len(out_data)
                for item in out_data:
                    status = item.get('status_processamento', '')
                    if 'sucesso' in status:
                        w_success += 1
                    elif 'erro' in status or 'sem_boleto' in status:
                        w_errors += 1
                    
                    # Track Unique Bases
                    insc = item.get('inscricao')
                    if insc:
                        processed_base_ids.add(get_base(insc))
                        
        except:
            pass
            
        total_processed += w_processed
        total_success += w_success
        total_errors += w_errors
        
        workers.append({
            "name": worker_id,
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
def start_process(mode: str = "SMART_RESUME"):
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

    # Start subprocess (RUN PARALLEL)
    try:
        current_process = subprocess.Popen(
            [sys.executable, "-u", "run_parallel.py", "--workers", "10"], 
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
    
    # Force kill everything related to our bots
    # Force kill everything related to our bots - WINDOWS
    subprocess.run(["taskkill", "/F", "/IM", "python.exe"])
    # Note: This kills ALL python processes, including the server itself if not careful, 
    # but since server is also python, we might commit suicide. 
    # Better: Kill the child process group if possible.
    
    if current_process:
        current_process.terminate()  # Graceful first
        try:
             current_process.wait(timeout=5)
        except:
             current_process.kill() # Force
    
    current_process = None
    return {"message": "Todos os processos foram interrompidos."}

@app.post("/api/reset")
def reset_data():
    global current_process
    if current_process is not None and current_process.poll() is None:
         raise HTTPException(status_code=400, detail="Cannot reset while process is running. Stop it first.")
    
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)
        
    return {"message": "Data reset successfully"}

@app.get("/api/logs")
def get_logs(source: str = "all"):
    logs_content = ""
    
    # Helper to safe read
    def read_safe(path, title=None):
        out = ""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    c = f.read()
                    if c:
                        if title: out += f"=== {title} ===\n"
                        # If filtering specific source, show more history. If all, show less.
                        limit = 10000 if source != "all" else 2000
                        out += c[-limit:] + "\n\n"
            except: pass
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
    try:
        from fpdf import FPDF
        from datetime import datetime
        from fastapi.responses import Response
        import re
        
        # Helper: Extract Zona from Inscricao
        def extract_zona_from_inscricao(inscricao):
            """Extrai zona da inscrição (primeiro(s) dígito(s) antes do setor)"""
            if not inscricao or len(inscricao) < 5:
                return "DESCONHECIDA"
            try:
                # Formato: ZONA(1-2) + SETOR(4) + LOTE(3) + UNID(3)
                # Exemplo: 3001200000 -> Zona 3
                # Zona é o primeiro dígito ou primeiros 2 dígitos
                if len(inscricao) >= 11:
                    # Tentar extrair zona (assumindo 1 dígito inicialmente)
                    return inscricao[0]
            except:
                return "DESCONHECIDA"
            return "DESCONHECIDA"
        
        # Parse params
        show_errors = include_errors.lower() == "true"
        
        # Parse columns
        selected_cols = columns.split(',')
        
        # Column Definitions: Label, Data Key (internal), Weight (approx relative size)
        COL_DEFS = {
            "inscricao": {"label": "Inscrição", "weight": 25},
            "lote": {"label": "Lote / Unid.", "weight": 20},
            "endereco": {"label": "Endereço", "weight": 55},
            "proprietario": {"label": "Proprietário", "weight": 45},
            "documento": {"label": "Documento", "weight": 25},
            "metragem": {"label": "Área (m²)", "weight": 15},
            "valor_venal": {"label": "Valor Venal", "weight": 25},
            "status": {"label": "Status", "weight": 25}
        }
        
        # Filter valid cols
        active_cols = []
        total_weight = 0
        for c in selected_cols:
        if c in COL_DEFS:
            active_cols.append((c, COL_DEFS[c]))
            total_weight += COL_DEFS[c]['weight']
            
    if not active_cols:
        # Fallback default
        active_cols = [("inscricao", COL_DEFS["inscricao"]), ("lote", COL_DEFS["lote"])]
        total_weight = 45

    # Calculate Widths (Total Page Width ~190mm)
    PAGE_WIDTH = 190
    col_widths = {}
    for c_key, c_def in active_cols:
        w = (c_def['weight'] / total_weight) * PAGE_WIDTH
        col_widths[c_key] = w

    # Load ALL data from shards
    import glob
    all_data = []
    output_files = glob.glob("saida_imoveis*.json")
    for out_f in output_files:
        try:
            with open(out_f, 'r', encoding='utf-8') as f:
                d = json.load(f)
                if isinstance(d, list): all_data.extend(d)
        except: pass

    if not all_data:
         raise HTTPException(status_code=404, detail="Nenhum dado para exportar")

    # Deduplicate
    unique_map = {}
    for item in all_data:
        if item.get('inscricao'):
            unique_map[item['inscricao']] = item
    
    data = list(unique_map.values())

    # Apply Filters
    if not show_errors:
        data = [i for i in data if 'sucesso' in i.get('status_processamento', '').lower() 
                and 'sucesso_desmembrado' not in i.get('status_processamento', '').lower()]

    if bairro:
        data = [i for i in data if bairro.lower() in (i.get('bairro') or '').lower()]
    if rua:
        data = [i for i in data if rua.lower() in (i.get('rua') or i.get('endereco') or '').lower()]

    if not data:
         raise HTTPException(status_code=404, detail="Nenhum dado encontrado com esses filtros")

    # === HIERARCHICAL GROUPING: ZONA -> BAIRRO -> ITEMS ===
    zona_hierarchy = {}
    for item in data:
        zona = extract_zona_from_inscricao(item.get('inscricao', ''))
        bairro_name = (item.get('bairro') or 'SEM BAIRRO').strip().upper()
        
        if zona not in zona_hierarchy:
            zona_hierarchy[zona] = {}
        if bairro_name not in zona_hierarchy[zona]:
            zona_hierarchy[zona][bairro_name] = []
        
        zona_hierarchy[zona][bairro_name].append(item)
    
    # Sort zonas
    sorted_zonas = sorted(zona_hierarchy.keys())
    
    # Sort items within each bairro by Quadra/Lote
    def get_item_sort_key(item):
        inscrip = item.get('inscricao', '00000000000')
        nome = item.get('nome_lote', '')
        
        # Extract Quadra
        q_match = re.search(r'Quadra\s*(\d+)', nome, re.IGNORECASE)
        q_val = int(q_match.group(1)) if q_match else 999999
        
        # Extract unit order
        try:
            unit_order = int(inscrip[-3:])
        except: 
            unit_order = 0
        
        base_insc = inscrip[:-3]
        return (q_val, base_insc, unit_order)
    
    # Sort items in each bairro
    for zona in zona_hierarchy:
        for bairro_name in zona_hierarchy[zona]:
            try:
                zona_hierarchy[zona][bairro_name].sort(key=get_item_sort_key)
            except:
                pass

    # Setup PDF
    class PDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 15)
            self.cell(0, 10, 'Relatório de Imóveis', 0, 1, 'C')
            
            filter_text = []
            if bairro: filter_text.append(f"Bairro: {bairro}")
            if rua: filter_text.append(f"Rua: {rua}")
            
            self.set_font('Arial', '', 10)
            if filter_text:
                self.cell(0, 6, "Filtros: " + " | ".join(filter_text), 0, 1, 'C')
                
            self.cell(0, 6, f'Gerado em: {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}', 0, 1, 'C')
            self.ln(5)

        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 10, f'Página {self.page_no()}/{{nb}}', 0, 0, 'C')

    pdf = PDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    
    def clean_text(text):
        if text is None: return ""
        return str(text).encode('latin-1', 'replace').decode('latin-1')

    def print_table_header():
        pdf.set_fill_color(200, 220, 255)
        pdf.set_font('Arial', 'B', 9)
        
        for c_key, c_def in active_cols:
            w = col_widths[c_key]
            pdf.cell(w, 7, clean_text(c_def['label']), 1, 0, 'C', True)
        
        pdf.ln()
        pdf.set_font('Arial', '', 8)
    
    def print_bairro_summary_table(zona_data):
        """Imprime tabela de resumo de bairros para uma zona"""
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(0, 6, 'Resumo de Bairros:', 0, 1, 'L')
        pdf.ln(2)
        
        # Header
        pdf.set_fill_color(180, 200, 230)
        pdf.set_font('Arial', 'B', 9)
        pdf.cell(140, 7, 'Bairro', 1, 0, 'L', True)
        pdf.cell(50, 7, 'Quantidade de Lotes', 1, 1, 'C', True)
        
        # Rows
        pdf.set_font('Arial', '', 8)
        sorted_bairros = sorted(zona_data.keys())
        for bairro_name in sorted_bairros:
            items = zona_data[bairro_name]
            count = len(items)
            
            pdf.cell(140, 6, clean_text(bairro_name), 1, 0, 'L')
            pdf.cell(50, 6, str(count), 1, 1, 'C')
        
        pdf.ln(5)

    # === RENDER PDF WITH HIERARCHY ===
    for zona in sorted_zonas:
        # Check if new page needed
        if pdf.get_y() > 250:
            pdf.add_page()
        
        # ZONA HEADER
        pdf.set_font('Arial', 'B', 14)
        pdf.set_fill_color(100, 150, 200)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 10, f"ZONA {zona}", 0, 1, 'L', True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)
        
        # BAIRRO SUMMARY TABLE
        print_bairro_summary_table(zona_hierarchy[zona])
        
        # DETAILED DATA BY BAIRRO
        sorted_bairros = sorted(zona_hierarchy[zona].keys())
        for bairro_name in sorted_bairros:
            items = zona_hierarchy[zona][bairro_name]
            
            # Check page break before bairro section
            if pdf.get_y() > 240:
                pdf.add_page()
            
            # BAIRRO HEADER
            pdf.set_font('Arial', 'B', 12)
            pdf.set_fill_color(220, 220, 220)
            pdf.cell(0, 8, clean_text(f"BAIRRO: {bairro_name}"), 0, 1, 'L', True)
            pdf.ln(2)
            
            # TABLE HEADER
            print_table_header()
            
            # ITEMS
            for item in items:
                inscricao = clean_text(item.get('inscricao', ''))
                nome_lote_full = item.get('nome_lote', '')
                
                # Prepare row data
                row_values = {}
                row_values['inscricao'] = inscricao
                
                # Lote Logic
                is_subunit = not inscricao.endswith("000")
                q_match = re.search(r'(Quadra\s*\d+)', nome_lote_full, re.IGNORECASE)
                
                lote_val = nome_lote_full
                if q_match:
                    lote_val = nome_lote_full.replace(q_match.group(1), "").strip()
                    lote_val = lote_val.replace("Lote", "").strip()
                
                if is_subunit:
                    lote_val = "UNID. " + inscricao[-3:]
                    pdf.set_text_color(80, 80, 80)
                else:
                    pdf.set_text_color(0, 0, 0)
                    if not lote_val.startswith("Lote"):
                        lote_val = "Lote " + lote_val
                
                row_values['lote'] = clean_text(lote_val)
                row_values['endereco'] = clean_text(item.get('endereco') or item.get('rua') or '-')
                row_values['proprietario'] = clean_text(item.get('nome_proprietario') or '-')
                row_values['documento'] = clean_text(item.get('cpf_cnpj') or '-')
                row_values['metragem'] = clean_text(item.get('metragem') or '-')
                row_values['valor_venal'] = clean_text(item.get('valor_venal') or '-')

                # Calculate row height
                max_lines = 1
                for c_key, c_def in active_cols:
                    txt = row_values.get(c_key, '')
                    w = col_widths[c_key]
                    lines = len(pdf.multi_cell(w, 5, txt, split_only=True))
                    if lines > max_lines: max_lines = lines
                
                if max_lines > 3: max_lines = 3
                row_height = max_lines * 5
                
                # Check Page Break
                if pdf.get_y() + row_height > 275:
                    pdf.add_page()
                    print_table_header()
                
                # Draw Cells
                y_top = pdf.get_y()
                current_x = pdf.get_x()
                
                for c_key, c_def in active_cols:
                    w = col_widths[c_key]
                    txt = row_values.get(c_key, '')
                    align = 'C' if c_key in ['inscricao', 'lote', 'documento', 'metragem'] else 'L'
                    
                    pdf.rect(current_x, y_top, w, row_height)
                    pdf.set_xy(current_x, y_top)
                    pdf.multi_cell(w, 5, txt, border=0, align=align)
                    
                    current_x += w
                
                pdf.set_xy(10, y_top + row_height)
            
            # Space after bairro section
            pdf.ln(5)
        
        # Space after zona section
        pdf.ln(8)

        try:
            pdf_content = pdf.output(dest='S').encode('latin-1')
        except:
            pdf_content = pdf.output(dest='S').encode('latin-1')

        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=relatorio_imoveis_filtrado.pdf"}
        )
    
    except Exception as e:
        import traceback
        error_detail = f"Erro ao gerar PDF: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(error_detail)  # Log to console
        raise HTTPException(status_code=500, detail=error_detail)

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
    uvicorn.run(app, host="0.0.0.0", port=8000)
