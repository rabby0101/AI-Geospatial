"""
Test the API with real queries
"""

import requests
import json

BASE_URL = "http://127.0.0.1:8001"


def test_health():
    """Test health endpoint"""
    print("=" * 60)
    print("Testing Health Endpoint")
    print("=" * 60)

    response = requests.get(f"{BASE_URL}/api/health")
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    print()


def test_datasets():
    """Test datasets endpoint"""
    print("=" * 60)
    print("Testing Datasets Endpoint")
    print("=" * 60)

    response = requests.get(f"{BASE_URL}/api/datasets")
    print(f"Status Code: {response.status_code}")
    datasets = response.json()
    print(f"Found {len(datasets)} datasets:")
    for ds in datasets:
        print(f"  - {ds['name']}: {ds.get('description', 'No description')}")
    print()


def test_query(question):
    """Test natural language query"""
    print("=" * 60)
    print(f"Testing Query: {question}")
    print("=" * 60)

    payload = {"question": question}

    try:
        response = requests.post(
            f"{BASE_URL}/api/query",
            json=payload,
            timeout=30
        )

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            print(f"Success: {result.get('success')}")
            print(f"Result Type: {result.get('result_type')}")

            if result.get('metadata'):
                print(f"Metadata: {json.dumps(result['metadata'], indent=2)}")

            if result.get('data'):
                data = result['data']
                if isinstance(data, dict) and data.get('type') == 'FeatureCollection':
                    features = data.get('features', [])
                    print(f"Found {len(features)} features")

                    if features:
                        print("\nFirst feature:")
                        print(json.dumps(features[0], indent=2))
                else:
                    print(f"Data: {json.dumps(data, indent=2)[:500]}...")

        else:
            print(f"Error: {response.text}")

    except Exception as e:
        print(f"Exception: {e}")

    print()


def test_sql_query():
    """Test direct SQL query"""
    print("=" * 60)
    print("Testing Direct SQL Query")
    print("=" * 60)

    sql = "SELECT * FROM vector.osm_hospitals"
    payload = {"sql": sql}

    try:
        response = requests.post(
            f"{BASE_URL}/api/execute-sql",
            json=payload,
            timeout=30
        )

        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            data = result.get('data', {})

            if isinstance(data, dict) and data.get('type') == 'FeatureCollection':
                features = data.get('features', [])
                print(f"Found {len(features)} hospitals")

                for feature in features:
                    props = feature.get('properties', {})
                    print(f"  - {props.get('name', 'Unknown')}")
        else:
            print(f"Error: {response.text}")

    except Exception as e:
        print(f"Exception: {e}")

    print()


if __name__ == "__main__":
    # Run all tests
    test_health()
    test_datasets()
    test_sql_query()

    # Test natural language queries
    test_query("Show all hospitals in Berlin")
    test_query("Find all German states")
    test_query("How many hospitals are there?")
