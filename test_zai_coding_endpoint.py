"""
Test Z.ai GLM-4.6V with Coding Plan Endpoint
Verifies the official SDK format matches documentation.
"""

import os
from dotenv import load_dotenv
from src.layer2_thinker.glm4v_handler import GLM4VHandler
from PIL import Image
import numpy as np

# Load environment
load_dotenv()

# Get credentials
api_key = os.getenv("ZAI_API_KEY")
base_url = os.getenv("ZAI_BASE_URL")

print("=" * 60)
print("Z.AI GLM-4.6V CODING ENDPOINT TEST")
print("=" * 60)
print(f"API Key: {api_key[:20]}..." if api_key else "❌ No API key")
print(f"Base URL: {base_url}")
print(f"Model: glm-4.6v-flashx")
print("=" * 60)

if not api_key:
    print("\n❌ ERROR: ZAI_API_KEY not found in .env")
    exit(1)

# Initialize handler
print("\n⏳ Initializing GLM4VHandler...")
handler = GLM4VHandler(
    api_key=api_key,
    model="glm-4.6v-flashx",
    api_base=base_url,
    temperature=0.7,
    max_retries=3
)
print("✅ Handler initialized")

# Create a simple test image (red square)
print("\n⏳ Creating test image...")
test_image = Image.new('RGB', (100, 100), color='red')
print(f"✅ Test image created: {test_image.size} {test_image.mode}")

# Test vision query
print("\n⏳ Sending vision query to Z.ai...")
print("   Query: 'What color is this image?'")

try:
    response = handler.generate_content(
        text="What color is this image?",
        image=test_image
    )
    
    if response:
        print("\n" + "=" * 60)
        print("✅ SUCCESS - Z.ai Response:")
        print("=" * 60)
        print(response)
        print("=" * 60)
        print(f"\n📊 Performance:")
        print(f"   Requests: {handler.request_count}")
        print(f"   Avg Latency: {handler.average_latency:.2f}s")
    else:
        print("\n❌ ERROR: No response received")
        
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)
