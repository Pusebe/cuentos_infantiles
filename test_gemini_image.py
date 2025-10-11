import asyncio
from google import genai
from google.genai import types
import os
from dotenv import load_dotenv

load_dotenv()

async def test_gemini_image():
    api_key = os.getenv('GEMINI_API_KEY')
    
    if not api_key:
        print("❌ No hay GEMINI_API_KEY en .env")
        return
    
    print(f"✅ API Key encontrada: {api_key[:10]}...")
    
    client = genai.Client(api_key=api_key)
    
    prompt = "A colorful cartoon dragon, children's book style"
    
    print("🧪 Intentando generar imagen...")
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-image',
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio="1:1")
            )
        )
        
        print(f"🔍 Response: {response}")
        print(f"🔍 Parts: {response.parts if hasattr(response, 'parts') else 'No parts'}")
        
        if response and response.parts:
            print("✅ ¡Gemini Image FUNCIONA!")
        else:
            print("❌ Gemini Image NO genera imágenes")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_gemini_image())
    