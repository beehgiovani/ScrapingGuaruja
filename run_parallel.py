import subprocess
import time
import signal
import os
import sys

# Force UTF-8 for Windows Console/Logs
sys.stdout.reconfigure(encoding='utf-8')

sys.path.append(os.path.join(os.getcwd(), 'src'))
from tor_manager import TorManager

def run_parallel(num_workers=3):
    # --- 1. Central Tor Management ---
    if os.environ.get("USE_TOR", "false").lower() == "true":
        print("🔧 Configurando Tor Central...", flush=True)
        tor = TorManager()
        
        # Force kill any existing Tor to ensure clean port binding
        print("🔪 Matando processos Tor antigos...", flush=True)
        try:
           subprocess.run(["taskkill", "/F", "/IM", "tor.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except: pass
        time.sleep(2)
        
        print("🚀 Iniciando serviço Tor (aguarde)...", flush=True)
        if tor.start():
            print("✅ Tor iniciado com sucesso! Portas liberadas.", flush=True)
        else:
            print("❌ Falha ao iniciar Tor. Os bots podem falhar se IP for bloqueado.", flush=True)
            time.sleep(3)
    else:
        print("ℹ️ Modo TOR desativado (usando Proxy/Direct).", flush=True)

    processes = []
    
    print(f"🚀 Iniciando {num_workers} bots paralelos...", flush=True)
    
    # Define trap for Ctrl+C to kill all children
    def signal_handler(sig, frame):
        print("\n🛑 Encerrando todos os bots...")
        for p in processes:
            p.terminate()
        
        # Force kill Tor on exit
        try:
            subprocess.run(["taskkill", "/F", "/IM", "tor.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except: pass
            
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)

    # Keep file handles alive to prevent GC from closing them
    log_files = []

    for i in range(num_workers):
        cmd = [sys.executable, "-u", "src/automacao_imoveis.py", "--shard", str(i), "--total", str(num_workers)]
        
        # Open separate log file for each worker with line buffering (Text Mode)
        log_file = open(f"logs/worker_{i}.log", "w", encoding="utf-8", buffering=1)
        log_files.append(log_file)
        
        # Prepare env with USE_TOR inherited from parent (Server)
        env = os.environ.copy()
        
        # Start detached process
        p = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, env=env)
        processes.append(p)
        print(f"✅ Bot {i} iniciado (PID: {p.pid}) - Log: worker_{i}.log")
        
        # Small delay to stagger startups
        time.sleep(2.0)

    print("\nTodos os bots estão rodando. Pressione Ctrl+C para parar.")
    
    # Wait for all
    try:
        for p in processes:
            p.wait()
    except KeyboardInterrupt:
        signal_handler(None, None)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=30, help='Number of workers')
    args = parser.parse_args()
    
    run_parallel(args.workers)
