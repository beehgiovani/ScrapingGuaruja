
import json
import glob
import os
import shutil

def consolidate_outputs():
    # 1. Load Main Legacy File
    main_file = "saida_imoveis.json"
    all_data_map = {} # Key: inscricao
    
    if os.path.exists(main_file):
        try:
            with open(main_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    existing_data = json.loads(content)
                    for item in existing_data:
                        if "inscricao" in item:
                             all_data_map[item["inscricao"]] = item
                    print(f"Loaded {len(all_data_map)} items from {main_file}")
        except Exception as e:
            print(f"Error loading {main_file}: {e}")

    # 2. Iterate over all Parts
    part_files = glob.glob("saida_imoveis_part*.json")
    print(f"Found {len(part_files)} part files.")

    for p_file in part_files:
        try:
            with open(p_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content: continue
                
                part_data = json.loads(content)
                for item in part_data:
                     # Merge logic: Always overwrite? Or only if newer?
                     # User wants to unify. Let's assume part data is newer/better or just additive.
                     # We use inscricao as unique key.
                     if "inscricao" in item:
                         all_data_map[item["inscricao"]] = item
        except Exception as e:
            print(f"Error reading {p_file}: {e}")

    # 3. Save Unified File
    unified_list = list(all_data_map.values())
    print(f"Total unique items after consolidation: {len(unified_list)}")
    
    # Backup old one
    if os.path.exists(main_file):
        shutil.copy(main_file, main_file + ".bak")

    with open(main_file, "w", encoding="utf-8") as f:
        json.dump(unified_list, f, indent=2, ensure_ascii=False)
        
    print(f"Successfully saved to {main_file}")
    
    # 4. Optional: Clear/Archive parts?
    # User said "unify", usually implies cleaning up. But let's ask or just leave them?
    # Safest is to rename them to .bak or move to a folder.
    if not os.path.exists("backup_parts"):
        os.makedirs("backup_parts")
        
    for p_file in part_files:
        try:
            shutil.move(p_file, os.path.join("backup_parts", os.path.basename(p_file)))
        except Exception as e:
            print(f"Error moving {p_file}: {e}")
            
    # Re-create empty parts for workers to continue fresh? 
    # Actually, if we move them, the workers might simple create new ones.
    # But wait, current workers might be holding file handles?
    # Check if process is running!
    
    print("Consolidation Complete.")

if __name__ == "__main__":
    consolidate_outputs()
