import json
import glob
import os
import sys
from collections import defaultdict

# Force UTF-8 for stdout
sys.stdout.reconfigure(encoding='utf-8')

def analyze_data():
    # 1. Identify Files
    part_files = glob.glob('saida_imoveis_part*.json')
    legacy_file = 'saida_imoveis.json'
    
    all_files = part_files + [legacy_file] if os.path.exists(legacy_file) else part_files
    
    print(f"🔍 Analyzing {len(all_files)} files...")
    
    unique_map = {}
    duplicates = 0
    total_records = 0
    
    status_counts = defaultdict(int)
    
    # 2. Iterate and Load
    for fpath in all_files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Normalize list
                items = []
                if isinstance(data, dict) and 'data' in data:
                    items = list(data['data'].values())
                elif isinstance(data, list):
                    items = data
                
                # print(f"  - {fpath}: {len(items)} records")
                total_records += len(items)
                
                for item in items:
                    insc = item.get('inscricao')
                    if not insc: continue
                    
                    # Prioritize 'sucesso' over others if duplicate exists
                    existing = unique_map.get(insc)
                    
                    if existing:
                        duplicates += 1
                        # If existing is NOT success, and new IS success, overwrite
                        # or if existing is 'pendente' and new is anything else...
                        curr_status = existing.get('status_processamento', '')
                        new_status = item.get('status_processamento', '')
                        
                        # Logic: Success > Anulada > Sem Boleto > Erro > Pendente
                        def rank(s):
                            s = s.lower() if s else ''
                            if 'sucesso' in s: return 10
                            if 'anulada' in s: return 5
                            if 'sem_boleto' in s: return 4
                            if 'erro' in s: return 1
                            return 0
                            
                        if rank(new_status) > rank(curr_status):
                            unique_map[insc] = item
                    else:
                        unique_map[insc] = item

        except Exception as e:
            print(f"  x Error reading {fpath}: {e}")

    # 3. Stats
    print("\n" + "="*40)
    print("📊 CONSOLIDATION RESULTS")
    print("="*40)
    print(f"Total Raw Records Read: {total_records}")
    print(f"Duplicates Ignored:     {duplicates}")
    print(f"Unique Lots (Final):    {len(unique_map)}")
    print("-" * 40)
    
    # Count Statuses
    for item in unique_map.values():
        st = item.get('status_processamento', 'UNKNOWN')
        status_counts[st] += 1
        
    print("STATUS BREAKDOWN:")
    for st, count in sorted(status_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {st:<30} : {count}")
        
    # Sub-unit Stats
    # Check how many main lots were split
    desmembrados = sum(1 for k, v in unique_map.items() if len(str(k)) > 11) # len 11 = ZZZZSSSSLOTE (standard 11 chars + 3 sub?) 
    # Actually inscricao standard is 11 chars: ZZZZSSSLL000 ??
    # Worker: inscricao = f"{zona}{setor}{lote_geo}000" where Z=variable, S=4, L=3. Total usually 11-12 digits?
    # Sub-unit adds suffix. Let's rely on status 'sucesso_desmembrado' for parents.
    
    parents_desmembrados = status_counts['sucesso_desmembrado']
    
    print("-" * 40)
    print("SUB-UNIT ANALYSIS:")
    
    # Identify sub-units by length or suffix logic?
    # Standard format logic from code:
    # zona + setor(4) + lote(3) + suffix(3)
    # Base suffix is '000'. Sub is '001', '002', etc.
    
    subs_found = 0
    parents_found = 0
    
    for insc in unique_map.keys():
        if str(insc).endswith("000"):
            parents_found += 1
        else:
            subs_found += 1
            
    print(f"  Base Lots (ending in '000'): {parents_found}")
    print(f"  Sub-Units (ending in != '000'): {subs_found}")
    
    print("="*40)

if __name__ == "__main__":
    analyze_data()
