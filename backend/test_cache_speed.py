import time
import requests

URL = "http://127.0.0.1:8000/api/v1/scan/history/GDXU"

# 🐢 REQUEST 1: Live API Pull (Cache Miss)
start_miss = time.time()
res_miss = requests.get(URL).json()
end_miss = time.time()
print(f"--- Call 1 (Cache Miss) ---")
print(f"Source Type: {res_miss.get('source')}")
print(f"Execution Latency: {(end_miss - start_miss) * 1000:.2f} ms\n")

# ⚡ REQUEST 2: Redis In-Memory Stream (Cache Hit)
time.sleep(0.5)  # Quick pause
start_hit = time.time()
res_hit = requests.get(URL).json()
end_hit = time.time()
print(f"--- Call 2 (Cache Hit) ---")
print(f"Source Type: {res_hit.get('source')}")
print(f"Execution Latency: {(end_hit - start_hit) * 1000:.2f} ms")