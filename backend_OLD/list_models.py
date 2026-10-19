from google import genai
import os
from dotenv import load_dotenv

# Initialize environment
current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(current_dir, ".env"))

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

print("Listing models...")
for m in client.models.list():
  if 'generateContent' in m.supported_actions:
    print(m.name)
