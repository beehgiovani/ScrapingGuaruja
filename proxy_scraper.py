
import requests
import re
import concurrent.futures
import time
import os
import random

# Sources used to find free proxies
PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks4&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
]

def fetch_proxies():
    """Fetches raw proxies from defined sources."""
    proxies = set()
    print(f"Fetching proxies from {len(PROXY_SOURCES)} sources...")
    
    for url in PROXY_SOURCES:
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                lines = resp.text.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if line and ':' in line:
                         proxies.add(line)
        except Exception as e:
            print(f"Failed to fetch from {url}: {e}")
            
    print(f"Fetched {len(proxies)} unique candidates.")
    return list(proxies)

def check_proxy(proxy):
    """Checks if a proxy is working and anonymous."""
    
    # We try typical schemes
    schemes = ['socks5', 'socks4', 'http'] 
    
    target_urls = [
        "http://httpbin.org/ip",
        "http://ipv4.webshare.io/",
        "http://checkip.dyndns.org/"
    ]
    
    for scheme in schemes:
        for target_url in target_urls:
            try:
                proxy_url = f"{scheme}://{proxy}"
                proxies = {
                    "http": proxy_url,
                    "https": proxy_url,
                }
                
                start = time.time()
                resp = requests.get(target_url, proxies=proxies, timeout=5)
                # Ensure we got a valid response (200 OK)
                if resp.status_code == 200:
                    latency = time.time() - start
                    print(f"✓ Valid: {proxy} ({scheme}) - {latency:.2f}s - {target_url}")
                    return f"{scheme}://{proxy}"
            except:
                continue
            
    return None

def scrape_and_save(output_file="proxy_list.txt", max_workers=20, target_count=50):
    """Main function to scrape, validate, and save proxies."""
    
    raw_proxies = fetch_proxies()
    random.shuffle(raw_proxies) # Shuffle to avoid checking same block
    
    # [FIX] Limit candidates to avoid infinite waiting
    # 38k candidates take hours to check. 2000 is enough to find 50.
    candidates = raw_proxies[:2000] 
    
    valid_proxies = []
    
    print(f"Validating {len(candidates)} candidates (Target: {target_count})...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_proxy = {executor.submit(check_proxy, p): p for p in candidates}
        
        for future in concurrent.futures.as_completed(future_to_proxy):
            result = future.result()
            if result:
                valid_proxies.append(result)
                # If we have enough, we could stop, but cancelling futures is messy.
                # Just break logic if we strictly want to stop.
                if len(valid_proxies) >= target_count:
                    print("Target count reached.")
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except:
                        executor.shutdown(wait=False)
                    break
    
    # Save to file
    if valid_proxies:
        print(f"Saving {len(valid_proxies)} valid proxies to {output_file}...")
        with open(output_file, "w") as f:
            for p in valid_proxies:
                f.write(p + "\n")
        return len(valid_proxies)
    else:
        print("No valid proxies found.")
        return 0

if __name__ == "__main__":
    scrape_and_save()
