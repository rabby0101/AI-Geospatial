"""
Test direct SQL queries to PostGIS
"""

import requests
import json

BASE_URL = "http://127.0.0.1:8001"

# Test direct SQL query
sql = "SELECT name, geometry FROM vector.admin_boundaries LIMIT 10"

print("Testing Direct SQL Query to PostGIS")
print("=" * 70)
print(f"SQL: {sql}")
print("=" * 70)

response = requests.post(
    f"{BASE_URL}/api/execute-sql",
    json={"sql": sql},
    timeout=30
)

if response.status_code == 200:
    result = response.json()
    print(f"✅ SUCCESS")

    data = result.get('data', {})
    if data.get('features'):
        print(f"\nGerman States in PostGIS:")
        for feature in data['features']:
            props = feature.get('properties', {})
            print(f"  - {props.get('name', 'Unknown')}")
    else:
        print(f"Data: {json.dumps(data, indent=2)}")
else:
    print(f"❌ Error: {response.status_code}")
    print(response.text)

print("\n" + "=" * 70)
print("✅ Direct PostGIS access working!")
print("=" * 70)
