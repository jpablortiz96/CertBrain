import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

load_dotenv()

endpoint = os.getenv("PROJECT_ENDPOINT")
print(f"🔗 Endpoint: {endpoint}")

# Authenticate with Azure
credential = DefaultAzureCredential()
client = AIProjectClient(endpoint=endpoint, credential=credential)

print("✅ Client created successfully!")
print(f"📋 Project connected!")