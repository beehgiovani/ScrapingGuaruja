# Proxy Configuration - Bright Data & File List

# Bright Data Credentials (Zones 1 & 2)
BRIGHTDATA_PROXY1 = "http://brd-customer-hl_cce6d772-zone-isp_proxy1:x79e9u2k8uon@brd.superproxy.io:33335"
BRIGHTDATA_PROXY2 = "http://brd-customer-hl_cce6d772-zone-isp_proxy2:hx6w256i9dya@brd.superproxy.io:33335"

# Load File Proxies
FILE_PROXIES = []
try:
    if os.path.exists("proxy_list.txt"):
        with open("proxy_list.txt", "r") as f:
            FILE_PROXIES = [line.strip() for line in f if line.strip()]
except Exception as e:
    pass # Silent fail if file doesn't exist or error reading

# Proxy List Setup
PROY_LIST = []

def get_proxy_for_worker(worker_id, attempt=0):
    """Get proxy configuration for a specific worker"""
    
    # 1. PRIORITY: FILE PROXIES (from Scraper or Manual)
    if FILE_PROXIES and len(FILE_PROXIES) > 0:
        # Round Robin or Hash-based assignment
        # Use (worker_id + attempt) to rotate if retrying
        idx = (worker_id + attempt) % len(FILE_PROXIES)
        proxy_str = FILE_PROXIES[idx]
        
        # Format: scheme://user:pass@host:port or scheme://host:port or host:port
        # Basic parsing
        p_type = 'file_proxy'
        p_host_port = proxy_str
        p_user = None
        p_pass = None
        
        # Cleanup scheme for display/host_port extraction
        if "://" in proxy_str:
            scheme, remainder = proxy_str.split("://", 1)
        else:
            scheme = "http"
            remainder = proxy_str
            
        # Parse User:Pass
        if "@" in remainder:
            auth, host_port = remainder.split("@", 1)
            p_host_port = host_port
            if ":" in auth:
                p_user, p_pass = auth.split(":", 1)
        else:
            p_host_port = remainder
            
        return {
            'http': proxy_str if "://" in proxy_str else f"{scheme}://{proxy_str}",
            'https': proxy_str if "://" in proxy_str else f"{scheme}://{proxy_str}",
            'host_port': p_host_port,
            'type': 'file_proxy',
            'user': p_user,
            'pass': p_pass
        }

    # 2. FALLBACK: Bright Data (Zones 1 & 2)
    
    # 0-9: Zone 1
    if 0 <= worker_id < 10:
        return {
            'http': BRIGHTDATA_PROXY1,
            'https': BRIGHTDATA_PROXY1,
            'host_port': 'brd.superproxy.io:33335',
            'type': 'brightdata1'
        }
    
    # 10-19: Zone 2
    elif 10 <= worker_id < 20:
        return {
            'http': BRIGHTDATA_PROXY2,
            'https': BRIGHTDATA_PROXY2,
            'host_port': 'brd.superproxy.io:33335',
            'type': 'brightdata2'
        }
        
    # 20+: Recirculate BrightData Zones (Zones 1 & 2 alternating)
    else:
        # Alterna entre Zone 1 e Zone 2 para balancear
        if worker_id % 2 == 0:
             return {
                'http': BRIGHTDATA_PROXY1,
                'https': BRIGHTDATA_PROXY1,
                'host_port': 'brd.superproxy.io:33335',
                'type': 'brightdata1'
            }
        else:
             return {
                'http': BRIGHTDATA_PROXY2,
                'https': BRIGHTDATA_PROXY2,
                'host_port': 'brd.superproxy.io:33335',
                'type': 'brightdata2'
            }
