import os
import requests
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash") # Let's see what model is actually in deepseek.py
print(f"Model from deepseek.py: gemini-2.5... wait")

with open('app/utils/deepseek.py', 'r') as f:
    for line in f:
        if 'GEMINI_MODEL =' in line:
            print(line.strip())
