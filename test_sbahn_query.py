#!/usr/bin/env python3
import requests
import json
import time

url = "http://localhost:8000/api/query"
payload = {"question": "find sbahn stations in berlin which have no hospitals within 3km"}

print("Testing S-Bahn query...")
print("=" * 60)
print(f"Query: {payload['question']}")
print("=" * 60)

start = time.time()
try:
    response = requests.post(url, json=payload, timeout=60)
    elapsed = time.time() - start

    print(f"Status Code: {response.status_code}")
    print(f"Response Time: {elapsed:.2f} seconds")
    print("\nResponse:")

    data = response.json()
    print(json.dumps(data, indent=2, default=str))

    # Extract key info
    if data.get("success"):
        print(f"\n✅ Query succeeded")
        print(f"   Feature count: {data.get('metadata', {}).get('count', 'N/A')}")
        print(f"   Layer name: {data.get('layer_name', 'N/A')}")
        if data.get('reasoning'):
            print(f"\n   Reasoning: {data.get('reasoning')}")
    else:
        print(f"\n❌ Query failed")

except Exception as e:
    elapsed = time.time() - start
    print(f"❌ Error: {e}")
    print(f"Response Time: {elapsed:.2f} seconds")
