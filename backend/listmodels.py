import google.generativeai as genai
import os

# Load Gemini API key from environment variable
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyDj4D6f6w3Nu0WpMzuyG31fdrkvMsM0YiY")  # Replace with your actual API key or ensure it's set in the environment
genai.configure(api_key=GEMINI_API_KEY)

# List available models
models = genai.list_models()
for model in models:
    print(model.name)