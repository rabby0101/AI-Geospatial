#!/usr/bin/env python3
"""
Test DEM API Endpoints
Demonstrates how to query DEM data through the API
"""

import requests
import json
from typing import Dict, Any

BASE_URL = "http://localhost:8000/api/dem"

def print_response(title: str, response: Dict[str, Any]):
    """Pretty print API response"""
    print("\n" + "=" * 80)
    print(f"📍 {title}")
    print("=" * 80)

    if response.get("success"):
        if "summary" in response:
            print(response["summary"])
        if "data" in response:
            print("\nData:")
            print(json.dumps(response["data"], indent=2))
    else:
        print(f"❌ Error: {response.get('error', 'Unknown error')}")


def test_dem_endpoints():
    """Test all DEM endpoints"""

    print("\n🌍 Testing Berlin DEM API Endpoints\n")

    # Test 1: Get DEM Info
    print("1️⃣ Getting DEM Information...")
    try:
        response = requests.get(f"{BASE_URL}/info").json()
        print(f"   ✅ DEM Available: {response.get('available')}")
        print(f"   ✅ Resolution: {response.get('resolution')}")
        print(f"   ✅ Capabilities: {len(response.get('capabilities', []))} features")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 2: List Available Files
    print("\n2️⃣ Checking Available DEM Files...")
    try:
        response = requests.get(f"{BASE_URL}/available-files").json()
        num_files = len(response.get("analysis_results", {}))
        print(f"   ✅ DEM File Found: {response.get('dem_available')}")
        print(f"   ✅ Analysis Results: {num_files} files")
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 3: Terrain Stats Query
    print("\n3️⃣ Querying Terrain Statistics...")
    try:
        response = requests.post(
            f"{BASE_URL}/query",
            params={"question": "What is the terrain like in Berlin?"}
        ).json()
        print_response("Terrain Analysis", response)
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 4: Slope Analysis
    print("\n4️⃣ Querying Slope Analysis...")
    try:
        response = requests.post(
            f"{BASE_URL}/query",
            params={"question": "Show me the slope analysis"}
        ).json()
        print_response("Slope Analysis", response)
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 5: Development Suitability
    print("\n5️⃣ Querying Development Suitability...")
    try:
        response = requests.post(
            f"{BASE_URL}/query",
            params={"question": "Which areas are suitable for development?"}
        ).json()
        print_response("Development Suitability", response)
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 6: Terrain Classification
    print("\n6️⃣ Querying Terrain Classification...")
    try:
        response = requests.post(
            f"{BASE_URL}/query",
            params={"question": "Classify the terrain for me"}
        ).json()
        print_response("Terrain Classification", response)
    except Exception as e:
        print(f"   ❌ Error: {e}")

    # Test 7: Direct Endpoints
    print("\n7️⃣ Testing Direct Endpoints...")
    endpoints = [
        ("/terrain-stats", "Terrain Stats"),
        ("/slope", "Slope Analysis"),
        ("/development-suitability", "Development Suitability"),
        ("/classification", "Terrain Classification"),
    ]

    for endpoint, name in endpoints:
        try:
            response = requests.get(f"{BASE_URL}{endpoint}").json()
            if response.get("success"):
                print(f"   ✅ {name}: Success")
            else:
                print(f"   ⚠️  {name}: {response.get('error')}")
        except Exception as e:
            print(f"   ❌ {name}: {e}")

    print("\n" + "=" * 80)
    print("✅ DEM API Tests Complete!")
    print("=" * 80)


def example_queries():
    """Show example DEM queries"""
    print("\n📚 Example DEM Queries\n")

    examples = [
        "What is the terrain like in Berlin?",
        "Show me the slope analysis",
        "Which areas are suitable for development?",
        "What are the flood risk areas?",
        "Classify the terrain for me",
        "What is the elevation range?",
        "Show steep areas",
        "Development suitability analysis",
    ]

    for i, query in enumerate(examples, 1):
        print(f"{i}. \"{query}\"")

    print("\n💡 Use any of these queries with the DEM API endpoint:")
    print(f"   POST {BASE_URL}/query?question=<your-question>")


if __name__ == "__main__":
    print("""
    ╔════════════════════════════════════════════════════════════════╗
    ║     Berlin DEM API Test Suite                                  ║
    ║     Tests DEM query endpoints                                  ║
    ╚════════════════════════════════════════════════════════════════╝
    """)

    # First show example queries
    example_queries()

    # Check if API is running
    print("\n⏳ Checking if API is running on localhost:8000...")
    try:
        response = requests.get("http://localhost:8000/api/dem/info", timeout=2)
        if response.status_code == 200:
            print("✅ API is running!\n")
            # Run tests
            test_dem_endpoints()
        else:
            print("❌ API returned error")
    except requests.exceptions.ConnectionError:
        print("\n❌ Cannot connect to API at localhost:8000")
        print("\nTo start the API, run:")
        print("   python app/main.py")
        print("\nOr:")
        print("   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nMake sure the API is running!")
