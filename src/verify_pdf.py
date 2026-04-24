
import os
import json
import shutil
import sys
from fastapi import HTTPException

# Mock data
test_data = [
    {
        "nome_lote": "Quadra 1 Lote Short",
        "inscricao": "11111",
        "cpf_cnpj": "00000000000",
        "nome_proprietario": "Short Name",
        "status_processamento": "sucesso"
    },
    {
        "nome_lote": "Quadra 1 Lote Very Long Name That Should Definitely Wrap To A Second Line Because It Is Over 25mm Width In Arial 8",
        "inscricao": "22222",
        "cpf_cnpj": "11111111111",
        "nome_proprietario": "Long Name Owner",
        "status_processamento": "sucesso"
    }
]

ORIGINAL_FILE = "saida_imoveis.json"
BACKUP_FILE = "saida_imoveis.json.bak"

def setup():
    if os.path.exists(ORIGINAL_FILE):
        shutil.move(ORIGINAL_FILE, BACKUP_FILE)
    
    with open(ORIGINAL_FILE, 'w', encoding='utf-8') as f:
        json.dump(test_data, f)

def teardown():
    if os.path.exists(ORIGINAL_FILE):
        os.remove(ORIGINAL_FILE)
    if os.path.exists(BACKUP_FILE):
        shutil.move(BACKUP_FILE, ORIGINAL_FILE)

def run_test():
    try:
        # Import server after file is set up
        import server
        
        print("Calling export_pdf()...")
        response = server.export_pdf()
        
        print("Response received.")
        print(f"Status Code: {response.status_code if hasattr(response, 'status_code') else 'OK'}") # Response object might not have status_code if it's a standard Response, but FastAPI response usually does or it's just bytes?
        # server.py returns `Response(content=..., media_type=...)`
        # verifying content length
        
        content = response.body
        print(f"PDF Content Length: {len(content)} bytes")
        
        if len(content) > 1000:
            print("SUCCESS: PDF generated and has content.")
            # Optional: Save it to inspect if needed (but I can't inspect)
            # with open("debug_output.pdf", "wb") as f:
            #     f.write(content)
        else:
            print("FAILURE: PDF content seems too small.")
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        teardown()

if __name__ == "__main__":
    setup()
    run_test()
