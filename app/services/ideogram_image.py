"""
Servicio para Ideogram - Generación de portadas con Character Reference
"""

import aiohttp
import aiofiles
import secrets
import time
import asyncio
from typing import Dict, Optional
from pathlib import Path
from ..config import settings


class IdeogramImageService:
    """Servicio para generación de portadas con Ideogram"""
    
    def __init__(self):
        if not settings.ideogram_api_key:
            raise ValueError("IDEOGRAM_API_KEY no configurada")
        
        self.api_key = settings.ideogram_api_key
        self.model = settings.ideogram_model_cover
        
        # Solo soportamos V3
        if not self.model.startswith('V_3'):
            raise ValueError(f"❌ Solo se soporta V_3_TURBO, modelo actual: {self.model}")
        
        self.base_url = "https://api.ideogram.ai/v1/ideogram-v3/generate"
        self.last_request = 0
        self.min_delay = 1
        
        print(f"🎨 Ideogram Service configurado (modelo: {self.model})")
    
    async def generate_cover(
        self, 
        story_data: Dict,
        reference_photo_path: Optional[str] = None
    ) -> Optional[str]:
        """
        Genera portada usando Ideogram V3 con character reference
        REQUIERE foto de referencia obligatoriamente
        """
        try:
            # Validar que hay foto
            if not reference_photo_path:
                print("❌ ERROR: No se proporcionó foto de referencia (reference_photo_path es None)")
                raise ValueError("Se requiere foto de referencia para generar portada")
            
            if not Path(reference_photo_path).exists():
                print(f"❌ ERROR: La foto de referencia no existe: {reference_photo_path}")
                raise ValueError(f"La foto de referencia no existe: {reference_photo_path}")
            
            child_name = story_data.get('child_name', 'el niño')
            tema = story_data.get('tema', 'aventura')
            titulo = story_data['titulo']
            age = story_data.get('age', 5)
            mundo_desc = story_data.get('mundo_descripcion', 'mundo mágico de aventuras')
            
            # TU PROMPT ORIGINAL
            prompt = f"""Crea una PORTADA DE LIBRO INFANTIL profesional y mágica.

TRANSFORMACIÓN ARTÍSTICA:
- Convierte a la persona de la foto en el protagonista estilo libro infantil moderno
- Referencias de estilo: Disney, Pixar, libros infantiles contemporáneos de alta calidad

HISTORIA:
- Título: "{titulo}"
- Tema: {tema}
- Mundo: {mundo_desc}
- Edad del lector: {age} años

COMPOSICIÓN:
- Mundo fantástico coherente con el tema de fondo
- Colores vibrantes, saturados y atractivos
- El título integrado artísticamente en la composición
- Atmósfera mágica que invite a la aventura
- Detalles ricos que capturen la imaginación

ESTILO VISUAL:
- Ilustración digital profesional de alta calidad
- Paleta de colores alegre y fantástica
- Iluminación cinematográfica
- Textura y profundidad visual
- Aspecto de portada premium de librería

MUY IMPORTANTE: - No pongas otro texto que no sea el título.

"""

            print(f"🎨 Generando portada con Ideogram ({self.model}) CON foto de referencia: {Path(reference_photo_path).name}")
            
            await self._respect_rate_limit()
            
            headers = {
                "Api-Key": self.api_key
            }
            
            result = await self._generate_with_character_reference(
                prompt=prompt,
                photo_path=reference_photo_path,
                headers=headers
            )
            
            # Extraer URL de la imagen
            if result and 'data' in result and len(result['data']) > 0:
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
            import traceback
            traceback.print_exc()
            return None
    
    async def _generate_with_character_reference(
        self, 
        prompt: str, 
        photo_path: str, 
        headers: dict
    ) -> Optional[dict]:
        """Genera con character reference usando multipart/form-data"""
        try:
            # Crear FormData
            data = aiohttp.FormData()
            
            # Añadir campos de texto
            data.add_field('prompt', prompt)
            data.add_field('aspect_ratio', '1x1')
            data.add_field('model', self.model)
            data.add_field('magic_prompt_option', 'OFF')
            data.add_field('style_type', 'FICTION')  # Requerido para character reference
            
            # Añadir la imagen como character reference
            with open(photo_path, 'rb') as f:
                image_data = f.read()
                data.add_field(
                    'character_reference_images',
                    image_data,
                    filename=Path(photo_path).name,
                    content_type='image/jpeg'
                )
            
            print(f"📤 Enviando request multipart a Ideogram con character reference")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.base_url, data=data, headers=headers) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        print(f"❌ Error de Ideogram API (multipart): {response.status} - {error_text}")
                        return None
                    
                    return await response.json()
                    
        except Exception as e:
            print(f"❌ Error en multipart request: {e}")
            import traceback
            traceback.print_exc()
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