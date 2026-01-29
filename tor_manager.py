#!/usr/bin/env python3
"""
Tor Manager - Manages Tor service for IP masking
Provides SOCKS5 proxy on port 9050 with IP rotation capability
"""

import subprocess
import time
import socket
import requests
import os
import shutil
from stem import Signal
from stem.control import Controller

class TorManager:
    """Manages Tor service and provides IP rotation"""
    
    SOCKS_PORT = 9150
    CONTROL_PORT = 9152
    TOR_PASSWORD = "250318Zz@"  # Change this for production
    
    def __init__(self):
        self.tor_process = None
        self.is_running = False
    
    def force_kill_tor(self):
        """Force kill any running Tor process"""
        print("🔪 Force killing existing tor.exe processes...")
        try:
             subprocess.run(["taskkill", "/F", "/IM", "tor.exe"], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
             time.sleep(1) # Wait for OS to release files
        except Exception as e:
             print(f"Error killing tor: {e}")

    def start(self):
        """Start Tor service locally using torrc"""
        try:
            # Check if Tor is already running AND healthy (both ports open)
            if self._check_tor_running(full_check=True):
                print("✓ Tor service is already running and healthy (SOCKS+Control)")
                self.is_running = True
                return True
            
            # If not healthy (maybe only one port open), kill it
            self.force_kill_tor()
            
            print("Starting Tor service (Local)...")
            
            # Check standard paths if 'tor' not in PATH
            tor_cmd = 'tor'
            if not shutil.which(tor_cmd):
                 base_search_paths = [
                     r"C:\Users\bruno\OneDrive\Área de Trabalho\Tor Browser",
                     r"C:\Users\bruno\Desktop\Tor Browser",
                     r"C:\Program Files\Tor Browser",
                     r"C:\Program Files (x86)\Tor Browser",
                     os.path.expanduser(r"~\Desktop\Tor Browser"),
                     os.path.expanduser(r"~\AppData\Local\Programs\Tor Browser")
                 ]

                 found_path = None
                 print("🔍 Searching for tor.exe in common locations...")
                 
                 for base in base_search_paths:
                     if os.path.exists(base):
                         # Walk to find tor.exe
                         for root, dirs, files in os.walk(base):
                             if "tor.exe" in files:
                                 found_path = os.path.join(root, "tor.exe")
                                 break
                         if found_path: break
                 
                 if found_path:
                     tor_cmd = found_path
                     print(f"found Tor at: {tor_cmd}")
                 else:
                     print("⚠ Could not auto-detect tor.exe. Trying fallback paths.")
                     # Fallback specific paths
                     fallback_paths = [
                         r"C:\Users\bruno\OneDrive\Área de Trabalho\Tor Browser\Browser\Tor\tor.exe",
                         r"C:\Users\bruno\OneDrive\Área de Trabalho\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
                         # User mentioned "firefox" name - adding as desperate fallback
                         r"C:\Users\bruno\OneDrive\Área de Trabalho\Tor Browser\Browser\firefox.exe"
                     ]
                     for p in fallback_paths:
                         if os.path.exists(p):
                             tor_cmd = p
                             break
            
            # Create data directory if not exists
            if not os.path.exists("tor_data"):
                os.makedirs("tor_data")
            
            # Use absolute path for torrc
            torrc_path = os.path.abspath("torrc")
            print(f"Using torrc config at: {torrc_path}")

            # Try to locate geoip files relative to tor.exe
            tor_dir = os.path.dirname(tor_cmd)
            geoip_path = os.path.join(tor_dir, 'geoip')
            geoip6_path = os.path.join(tor_dir, 'geoip6')
            
            # If standard ones don't exist, check Tor Browser structure
            # often in Data/Tor/geoip or similar
            if not os.path.exists(geoip_path):
                 # Try finding them in the tree
                 for root, dirs, files in os.walk(os.path.dirname(tor_dir)):
                     if 'geoip' in files:
                         geoip_path = os.path.join(root, 'geoip')
                     if 'geoip6' in files:
                         geoip6_path = os.path.join(root, 'geoip6')
            
            extra_args = []
            if os.path.exists(geoip_path):
                print(f"Found geoip at: {geoip_path}")
                extra_args.extend(['--GeoIPFile', geoip_path])
            if os.path.exists(geoip6_path):
                 extra_args.extend(['--GeoIPv6File', geoip6_path])

            # Start Tor as a local process
            cmd_args = [tor_cmd, '-f', torrc_path] + extra_args
            print(f"Executing: {' '.join(cmd_args)}")
            
            self.tor_process = subprocess.Popen(
                cmd_args, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                cwd=os.getcwd()
            )
            
            # Wait for Tor to be ready
            for i in range(90):
                time.sleep(1)
                # Check BOTH ports
                if self._check_tor_running(full_check=True):
                    print(f"✓ Tor service started successfully (took {i+1}s)")
                    self.is_running = True
                    return True
                
                # Check if process died
                if self.tor_process.poll() is not None:
                     out, err = self.tor_process.communicate()
                     # Try to read stdout/stderr from pipe if available
                     print(f"✗ Tor died immediately. Exit Code: {self.tor_process.returncode}")
                     if out: print(f"STDOUT: {out.decode('utf-8', errors='replace')}")
                     if err: print(f"STDERR: {err.decode('utf-8', errors='replace')}")
                     return False
            
            # Verify actual connectivity
            print("⏳ Verifying Tor connectivity (fetching IP)...")
            current_ip = self.get_current_ip(use_tor=True)
            if current_ip:
                print(f"✓ Tor Connected! IP: {current_ip}")
                self.is_running = True
                return True
            else:
                 print("⚠ Tor process running but IP fetch failed. It might be too slow.")
                 # We return True anyway to let bots try, but warn.
                 self.is_running = True
                 return True
            
            # If still not running but process matches
            print("✗ Tor service failed to start within 90 seconds (Port 9150 not open).")
            # Try to grab last logs
            if self.tor_process:
                 try:
                     self.tor_process.terminate()
                     out, err = self.tor_process.communicate()
                     if out: print(f"STDOUT Last: {out.decode('utf-8', errors='replace')}")
                     if err: print(f"STDERR Last: {err.decode('utf-8', errors='replace')}")
                 except: pass
            return False
            
        except FileNotFoundError:
            print("✗ 'tor' command not found. Please install tor: sudo apt install tor")
            return False
        except Exception as e:
            print(f"✗ Failed to start Tor service: {e}")
            return False
    
    def stop(self):
        """Stop Tor service"""
        try:
            print("Stopping Tor service...")
            
            # Method 1: Kill child process if we own it
            if self.tor_process:
                self.tor_process.terminate()
                self.tor_process = None
            
            # Method 2: Force kill by port just in case (orphaned)
            subprocess.run(["fuser", "-k", f"{self.SOCKS_PORT}/tcp"], capture_output=True)
            
            self.is_running = False
            print("✓ Tor service stopped")
            return True
        except Exception as e:
            print(f"✗ Failed to stop Tor service: {e}")
            return False
    
    def restart(self):
        """Restart Tor service"""
        self.stop()
        time.sleep(2)
        return self.start()
    
    def _check_tor_running(self, full_check=False):
        """Check if Tor SOCKS proxy (and optionally Control) is accessible"""
        try:
            # Check SOCKS
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', self.SOCKS_PORT))
            sock.close()
            
            if result != 0: return False
            
            if full_check:
                # Check Control Port too
                sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock2.settimeout(1)
                result2 = sock2.connect_ex(('127.0.0.1', self.CONTROL_PORT))
                sock2.close()
                return result2 == 0
                
            return True
        except:
            return False
    
    def get_current_ip(self, use_tor=True):
        """Get current public IP address"""
        try:
            if use_tor:
                proxies = {
                    'http': f'socks5h://127.0.0.1:{self.SOCKS_PORT}',
                    'https': f'socks5h://127.0.0.1:{self.SOCKS_PORT}'
                }
                response = requests.get('https://api.ipify.org?format=json', 
                                       proxies=proxies, timeout=10)
            else:
                response = requests.get('https://api.ipify.org?format=json', timeout=10)
            
            if response.status_code == 200:
                return response.json()['ip']
            return None
        except Exception as e:
            print(f"Error getting IP: {e}")
            return None
    
    def rotate_ip(self):
        """Request a new Tor circuit (change IP)"""
        try:
            with Controller.from_port(port=self.CONTROL_PORT) as controller:
                controller.authenticate()
                controller.signal(Signal.NEWNYM)
                print("✓ Tor IP rotation requested")
                time.sleep(3)  # Wait for new circuit
                return True
                return True
        except ConnectionRefusedError:
             print("✗ IP Rotation Failed: Could not connect to Tor Control Port (9152).")
             print("  -> Is Tor running? Is 'ControlPort 9152' enabled in torrc?")
             return False
        except Exception as e:
            print(f"✗ Failed to rotate IP: {e}")
            print("Note: IP rotation requires Tor control port configuration")
            return False
    
    def get_proxy_config(self):
        """Get proxy configuration for Playwright"""
        if not self.is_running:
            raise RuntimeError("Tor service is not running")
        
        return {
            'server': f'socks5://127.0.0.1:{self.SOCKS_PORT}'
        }
    
    def status(self):
        """Get Tor service status"""
        is_running = self._check_tor_running()
        
        status_info = {
            'running': is_running,
            'socks_port': self.SOCKS_PORT,
            'control_port': self.CONTROL_PORT
        }
        
        if is_running:
            current_ip = self.get_current_ip(use_tor=True)
            real_ip = self.get_current_ip(use_tor=False)
            status_info['tor_ip'] = current_ip
            status_info['real_ip'] = real_ip
            status_info['masked'] = current_ip != real_ip if (current_ip and real_ip) else None
        
        return status_info


def main():
    """CLI interface for Tor manager"""
    import sys
    
    manager = TorManager()
    
    if len(sys.argv) < 2:
        print("Usage: python3 tor_manager.py [start|stop|restart|status|rotate|ip]")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'start':
        success = manager.start()
        sys.exit(0 if success else 1)
    
    elif command == 'stop':
        success = manager.stop()
        sys.exit(0 if success else 1)
    
    elif command == 'restart':
        success = manager.restart()
        sys.exit(0 if success else 1)
    
    elif command == 'status':
        status = manager.status()
        print("\n=== Tor Status ===")
        print(f"Running: {status['running']}")
        print(f"SOCKS Port: {status['socks_port']}")
        print(f"Control Port: {status['control_port']}")
        
        if status['running']:
            print(f"\nReal IP: {status.get('real_ip', 'N/A')}")
            print(f"Tor IP: {status.get('tor_ip', 'N/A')}")
            print(f"IP Masked: {status.get('masked', 'N/A')}")
        
        sys.exit(0 if status['running'] else 1)
    
    elif command == 'rotate':
        if not manager._check_tor_running():
            print("✗ Tor is not running. Start it first with: python3 tor_manager.py start")
            sys.exit(1)
        
        old_ip = manager.get_current_ip(use_tor=True)
        print(f"Current IP: {old_ip}")
        
        manager.rotate_ip()
        
        new_ip = manager.get_current_ip(use_tor=True)
        print(f"New IP: {new_ip}")
        
        if old_ip != new_ip:
            print("✓ IP successfully rotated")
        else:
            print("⚠ IP did not change (may take a few moments)")
        
        sys.exit(0)
    
    elif command == 'ip':
        if not manager._check_tor_running():
            print("✗ Tor is not running. Start it first with: python3 tor_manager.py start")
            sys.exit(1)
        
        tor_ip = manager.get_current_ip(use_tor=True)
        real_ip = manager.get_current_ip(use_tor=False)
        
        print(f"Real IP: {real_ip}")
        print(f"Tor IP: {tor_ip}")
        
        if tor_ip and real_ip and tor_ip != real_ip:
            print("✓ IP is successfully masked")
        elif tor_ip and real_ip and tor_ip == real_ip:
            print("✗ WARNING: IP is NOT masked!")
        
        sys.exit(0)
    
    else:
        print(f"Unknown command: {command}")
        print("Usage: python3 tor_manager.py [start|stop|restart|status|rotate|ip]")
        sys.exit(1)


if __name__ == '__main__':
    main()
