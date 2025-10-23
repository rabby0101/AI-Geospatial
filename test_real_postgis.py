"""
Test API with Real PostGIS Data
"""

import requests
import json

BASE_URL = "http://127.0.0.1:8001"

def test_query(question):
    """Test a query and show results"""
    print("\n" + "=" * 70)
    print(f"Query: \"{question}\"")
    print("=" * 70)

    response = requests.post(
        f"{BASE_URL}/api/query",
        json={"question": question},
        timeout=30
    )

    if response.status_code == 200:
        result = response.json()

        if result.get('success'):
            print(f"✅ SUCCESS")
            metadata = result.get('metadata', {})
            print(f"   Count: {metadata.get('count', 0)}")

            data = result.get('data', {})
            if data.get('features'):
                features = data['features'][:3]
                print(f"\n   Sample Results:")
                for i, f in enumerate(features, 1):
                    props = f.get('properties', {})
                    print(f"   {i}. {props.get('name', 'Unknown')}")
                    if 'country_code' in props:
                        print(f"      Country: {props['country_code']}")
        else:
            print(f"❌ FAILED: {result.get('error', 'Unknown error')}")
    else:
        print(f"❌ HTTP {response.status_code}")

# Test queries
print("\n🌍 Testing Cognitive Geospatial Assistant with Real PostGIS Data")
print("=" * 70)

test_query("Show all hospitals")
test_query("Find German states")
test_query("List all administrative boundaries")
test_query("How many German states are there?")
test_query("Show me Berlin")

print("\n" + "=" * 70)
print("✅ Tests Complete!")
print("=" * 70)
