"""
Live Demo: Cognitive Geospatial Assistant API
Showcasing natural language to geospatial queries
"""

import requests
import json
import time

BASE_URL = "http://127.0.0.1:8001"

def print_header(text):
    """Print a nice header"""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)

def print_success(text):
    """Print success message"""
    print(f"✅ {text}")

def print_info(text):
    """Print info message"""
    print(f"ℹ️  {text}")

def test_query(question, show_details=True):
    """Test a natural language query and show results"""
    print_header(f'Query: "{question}"')

    start = time.time()

    try:
        response = requests.post(
            f"{BASE_URL}/api/query",
            json={"question": question},
            timeout=30
        )

        elapsed = time.time() - start

        if response.status_code == 200:
            result = response.json()

            if result.get('success'):
                print_success(f"Query successful! (Executed in {elapsed:.2f}s)")

                metadata = result.get('metadata', {})
                print_info(f"Found: {metadata.get('count', 0)} features")

                if metadata.get('bounds'):
                    bounds = metadata['bounds']
                    print_info(f"Bounds: [{bounds[0]:.4f}, {bounds[1]:.4f}, {bounds[2]:.4f}, {bounds[3]:.4f}]")

                data = result.get('data', {})
                if data.get('type') == 'FeatureCollection':
                    features = data.get('features', [])

                    if features and show_details:
                        print(f"\n📍 Sample Features:")
                        for i, feature in enumerate(features[:3], 1):
                            props = feature.get('properties', {})
                            geom = feature.get('geometry', {})

                            print(f"\n  {i}. {props.get('name', 'Unnamed')}")
                            if 'city' in props:
                                print(f"     City: {props['city']}")
                            if 'amenity' in props:
                                print(f"     Type: {props['amenity']}")
                            if geom.get('coordinates'):
                                coords = geom['coordinates']
                                print(f"     Location: ({coords[0]:.4f}, {coords[1]:.4f})")

                        if len(features) > 3:
                            print(f"\n  ... and {len(features) - 3} more")

                return True
            else:
                print(f"❌ Query failed: {result.get('error', 'Unknown error')}")
                return False
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            print(f"   {response.text[:200]}")
            return False

    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def main():
    """Run the demo"""
    print("\n" + "🌍" * 35)
    print_header("COGNITIVE GEOSPATIAL ASSISTANT API - LIVE DEMO")
    print("🌍" * 35)

    # Check health
    print_header("1. Health Check")
    try:
        response = requests.get(f"{BASE_URL}/api/health", timeout=5)
        health = response.json()

        if health.get('status') == 'healthy':
            print_success("API is running")
            print_success(f"Database: {health.get('database')}")
        else:
            print(f"⚠️  API Status: {health.get('status')}")
            return
    except Exception as e:
        print(f"❌ Cannot connect to API: {e}")
        print(f"   Make sure server is running on {BASE_URL}")
        return

    # Demo queries
    print_header("2. Natural Language Geospatial Queries")

    queries = [
        ("Show all hospitals in Berlin", True),
        ("How many hospitals are there?", False),
        ("Find hospitals", True),
        ("List all hospitals with their names", True),
    ]

    success_count = 0
    for question, show_details in queries:
        if test_query(question, show_details):
            success_count += 1
        time.sleep(1)  # Small delay between queries

    # Summary
    print_header("DEMO SUMMARY")
    print(f"✅ Successful Queries: {success_count}/{len(queries)}")
    print(f"🤖 DeepSeek AI: Converting natural language to geospatial operations")
    print(f"🗄️  PostGIS: Executing spatial SQL queries")
    print(f"🌍 GeoJSON: Returning map-ready geographic data")

    print("\n" + "=" * 70)
    print("  API Documentation: http://127.0.0.1:8001/docs")
    print("  Interactive Swagger UI with all endpoints")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
