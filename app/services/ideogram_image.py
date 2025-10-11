"""
Servicio para Ideogram - Generación de portadas
"""

import requests
import aiofiles
import secrets
import time
import asyncio
from typing import Dict, Optional
from ..config import settings


class IdeogramImageService:
    """Servicio para generación de portadas con Ideogram"""
    
    def __init__(self):
        if not settings.ideogram_api_key:
            raise ValueError("IDEOGRAM_API_KEY no configurada")
        
        self.api_key = settings.ideogram_api_key
        self.model = settings.ideogram_model_cover
        self.base_url = "https://api.ideogram.ai/v1/ideogram-v3/generate"
        self.last_request = 0
        self.min_delay = 1
        
        print(f"🎨 Ideogram Service configurado (modelo: {self.model})")
    
    async def generate_cover(
        self, 
        story_data: Dict
    ) -> Optional[str]:
        """
        Genera portada usando Ideogram (JSON API)
        """
        try:
            child_name = story_data.get('child_name', 'el niño')
            tema = story_data.get('tema', 'aventura')
            titulo = story_data['titulo']
            age = story_data.get('age', 5)
            
            # Obtener descripciones
            protagonista = story_data.get('protagonista', {})
            descripcion_fisica = protagonista.get('descripcion_fisica', f'{child_name}, el protagonista')
            mundo_desc = story_data.get('mundo_descripcion', 'mundo mágico de aventuras')
            
            prompt = f"""Children's book cover illustration, professional quality.

MAIN CHARACTER:
- Name: {child_name}
- Physical description: {descripcion_fisica}
- Style: Disney/Pixar animated character, colorful and expressive
- Position: front and center (60% of image), dynamic pose

STORY WORLD:
- Title: "{titulo}"
- Theme: {tema}
- Setting: {mundo_desc}
- Background: magical fantasy world matching the theme

VISUAL STYLE:
- High quality digital illustration
- Vibrant colors and cinematic lighting
- Professional children's book cover aesthetic
- Age appropriate for {age} years old
- Rich details and textures

COMPOSITION:
- Title "{titulo}" integrated artistically in the image
- Character in foreground, fantasy world in background
- Inviting and magical atmosphere

Style references: Disney, Pixar, modern children's books"""

            print(f"🎨 Generando portada con Ideogram ({self.model})...")
            
            await self._respect_rate_limit()
            
            headers = {
                "Api-Key": self.api_key
            }
            
            # V3 usa multipart, otros usan JSON
            if self.use_multipart:
                # Multipart form para V3
                data = aiohttp.FormData()
                data.add_field('prompt', prompt)
                data.add_field('aspect_ratio', 'ASPECT_1_1')
                data.add_field('magic_prompt_option', 'AUTO')
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.base_url, data=data, headers=headers) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            print(f"❌ Error de Ideogram API: {response.status} - {error_text}")
                            return None
                        
                        result = await response.json()
            else:
                # JSON para V2_TURBO y anteriores
                headers["Content-Type"] = "application/json"
                payload = {
                    "image_request": {
                        "model": self.model,
                        "prompt": prompt,
                        "aspect_ratio": "ASPECT_1_1",
                        "magic_prompt_option": "AUTO"
                    }
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.base_url, json=payload, headers=headers) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            print(f"❌ Error de Ideogram API: {response.status} - {error_text}")
                            return None
                        
                                                
                        result = await response.json()
            
            # Extraer URL de la imagen
            if 'data' in result and len(result['data']) > 0:
                image_url = result['data'][0].get('url')
                
                if image_url:
                    # Descargar la imagen
                    filename = await self._download_image(image_url, child_name)
                    
                    if filename:
                        print(f"✅ Portada generada con Ideogram: {filename}")
                        return filename
            
            print("❌ No se pudo extraer URL de imagen de Ideogram")
            print(f"🔍 Response: {result}")
            return None
            
        except Exception as e:
            print(f"❌ Error generando portada con Ideogram: {e}")
            return None
    
    async def _download_image(self, image_url: str, child_name: str) -> Optional[str]:
        """Descargar imagen desde URL de Ideogram"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as response:
                    if response.status != 200:
                        print(f"❌ Error descargando imagen: {response.status}")
                        return None
                    
                    image_data = await response.read()
                    
                    # Guardar imagen
                    filename = f"cover_{secrets.token_urlsafe(8)}.png"
                    file_path = settings.previews_dir / filename
                    
                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(image_data)
                    
                    return filename
                    
        except Exception as e:
            print(f"❌ Error descargando imagen: {e}")
            return None
    
    async def _respect_rate_limit(self):
        """Rate limiting"""
        now = time.time()
        time_since_last = now - self.last_request
        
        if time_since_last < self.min_delay:
            wait_time = self.min_delay - time_since_last
            await asyncio.sleep(wait_time)
        
        self.last_request = time.time()