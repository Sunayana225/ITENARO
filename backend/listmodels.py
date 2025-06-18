import google.generativeai as genai
import os

# Load Gemini API key from environment variable (REQUIRED)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is required")
genai.configure(api_key=GEMINI_API_KEY)

# List available models
models = genai.list_models()
for model in models:
    print(model.name)