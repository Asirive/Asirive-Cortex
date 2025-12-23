"""
Test Kokoro TTS initialization and generation with debug logging.
"""
import logging
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

logger = logging.getLogger(__name__)

def test_kokoro_initialization():
    """Test Kokoro TTS step by step."""
    print("\n" + "="*60)
    print("KOKORO TTS DEBUG TEST")
    print("="*60 + "\n")
    
    # Step 1: Import
    print("Step 1: Importing KokoroTTS handler...")
    try:
        from layer1_reflex.kokoro_handler import KokoroTTS
        print("✅ Import successful\n")
    except ImportError as e:
        print(f"❌ Import failed: {e}\n")
        return False
    
    # Step 2: Create instance
    print("Step 2: Creating KokoroTTS instance...")
    try:
        tts = KokoroTTS(lang_code="a", default_voice="af_alloy")
        print(f"✅ Instance created: {tts}\n")
    except Exception as e:
        print(f"❌ Instance creation failed: {e}\n")
        return False
    
    # Step 3: Check initial state
    print("Step 3: Checking initial pipeline state...")
    print(f"   Pipeline: {tts.pipeline}")
    print(f"   Initialized: {tts._initialized}")
    print()
    
    # Step 4: Load pipeline
    print("Step 4: Loading pipeline...")
    try:
        success = tts.load_pipeline()
        print(f"   load_pipeline() returned: {success}")
        print(f"   Pipeline after load: {tts.pipeline}")
        print()
        
        if not success:
            print("❌ Pipeline loading failed\n")
            return False
        
        print("✅ Pipeline loaded\n")
    except Exception as e:
        print(f"❌ Pipeline loading failed: {e}\n")
        import traceback
        traceback.print_exc()
        return False
    
    # Step 5: Test generation
    print("Step 5: Testing speech generation...")
    try:
        test_text = "Hello, this is a test."
        print(f"   Test text: '{test_text}'")
        
        audio = tts.generate_speech(test_text)
        
        if audio is None:
            print("❌ Generation returned None\n")
            return False
        
        print(f"✅ Generation successful")
        print(f"   Audio shape: {audio.shape}")
        print(f"   Audio type: {type(audio)}")
        print(f"   Audio dtype: {audio.dtype}")
        print()
        
    except Exception as e:
        print(f"❌ Generation failed: {e}\n")
        import traceback
        traceback.print_exc()
        return False
    
    print("="*60)
    print("✅ ALL TESTS PASSED")
    print("="*60)
    return True

if __name__ == "__main__":
    success = test_kokoro_initialization()
    sys.exit(0 if success else 1)
