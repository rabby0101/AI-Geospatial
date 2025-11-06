#!/usr/bin/env python3
"""
Test script to verify LLM provider integration
Tests both DeepSeek and Gemma3 providers
"""

import requests
import json
import time

API_URL = "http://localhost:8000/api"

def test_provider(provider: str, query: str = "Find parks in Berlin"):
    """Test a specific LLM provider"""
    print(f"\n{'='*60}")
    print(f"Testing {provider.upper()} Provider")
    print(f"{'='*60}")

    payload = {
        "question": query,
        "llm_provider": provider
    }

    print(f"Query: {query}")
    print(f"Provider: {provider}")
    print(f"Sending request...")

    try:
        start_time = time.time()
        response = requests.post(
            f"{API_URL}/query",
            json=payload,
            timeout=120
        )
        elapsed = time.time() - start_time

        print(f"Status: {response.status_code}")
        print(f"Response time: {elapsed:.2f}s")

        if response.status_code == 200:
            data = response.json()
            print(f"\n✅ SUCCESS")
            print(f"Success: {data.get('success')}")
            print(f"Layer name: {data.get('layer_name')}")
            print(f"Features found: {len(data.get('data', {}).get('features', []))}")
            print(f"Metadata: {data.get('metadata', {})}")
            print(f"Reasoning: {data.get('reasoning', '')[:100]}...")
            return True
        else:
            print(f"❌ Error: {response.text}")
            return False

    except requests.exceptions.Timeout:
        print(f"❌ Request timeout (120s)")
        return False
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    print("\n" + "="*60)
    print("LLM Provider Integration Test")
    print("="*60)

    # Test health check
    print("\n📋 Checking API Health...")
    try:
        health = requests.get(f"{API_URL}/health").json()
        print(f"API Status: {health.get('status')}")
        print(f"API Running: {health.get('api')}")
    except Exception as e:
        print(f"⚠️  Health check failed: {e}")

    # Test both providers
    deepseek_ok = test_provider("deepseek", "Show parks in Berlin")
    print("\n⏳ Waiting 5 seconds before testing Gemma3...")
    time.sleep(5)
    gemma3_ok = test_provider("gemma3", "Show parks in Berlin")

    # Summary
    print(f"\n{'='*60}")
    print("Test Summary")
    print(f"{'='*60}")
    print(f"DeepSeek: {'✅ PASSED' if deepseek_ok else '❌ FAILED'}")
    print(f"Gemma3:   {'✅ PASSED' if gemma3_ok else '❌ FAILED'}")
    print(f"\nIntegration Status: {'✅ ALL TESTS PASSED' if (deepseek_ok and gemma3_ok) else '⚠️  SOME TESTS FAILED'}")
