import json
import glob
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

def analyze_duplicates():
    part_files = glob.glob('saida_imoveis_part*.json')
    legacy_file = 'saida_imoveis.json'
    all_files = part_files + [legacy_file] if os.path.exists(legacy_file) else part_files
    
    unique_map = {}
    
    stats = {
        "exact_match": 0,
        "content_mismatch": 0,
        "total_duplicates": 0
    }
    
    print(f"🔍 Checking duplicates across {len(all_files)} files...")
    
    for fpath in all_files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                items = []
                if isinstance(data, dict) and 'data' in data:
                    items = list(data['data'].values())
                elif isinstance(data, list):
                    items = data
                
                for item in items:
                    insc = item.get('inscricao')
                    if not insc: continue
                    
                    # Normalize for comparison (remove transient fields if any, but we compare full dict for now)
                    # We sort keys to ensure order doesn't matter
                    item_str = json.dumps(item, sort_keys=True)
                    
                    if insc in unique_map:
                        existing_str = unique_map[insc]
                        stats["total_duplicates"] += 1
                        
                        if item_str == existing_str:
                            stats["exact_match"] += 1
                        else:
                            stats["content_mismatch"] += 1
                    else:
                        unique_map[insc] = item_str
                        
        except Exception as e:
            print(f"Error reading {fpath}: {e}")

    print("\n📊 DUPLICATE ANALYSIS")
    print("-" * 30)
    print(f"Total Duplicates Found:   {stats['total_duplicates']}")
    print(f"✅ Exact Identical:       {stats['exact_match']}")
    print(f"⚠️  Content Differs:      {stats['content_mismatch']}")
    print("-" * 30)
    
    if stats['content_mismatch'] > 0:
        print("Note: 'Content Differs' means the same lot appears with different statuses or data in different files.")

if __name__ == "__main__":
    analyze_duplicates()
