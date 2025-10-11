"""
Servicio para Gemini Image - Generación de imágenes
"""

from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFont
import asyncio
import aiofiles
import secrets
import time
from typing import Dict, Optional
from ..config import settings


class GeminiImageService:
    """Servicio para generación de imágenes con Gemini 2.5 Flash Image"""
    
    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY no configurada")
        
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.last_request = 0
        self.min_delay = 1
        print("🎨 Gemini Image Service configurado")
    
    async def generate_cover(
        self, 
        story_data: Dict, 
        reference_photo_path: str
    ) -> Optional[str]:
        """
        Genera portada TRANSFORMANDO al niño de la foto en personaje ilustrado
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
            
            prompt = f"""Crea una PORTADA DE LIBRO INFANTIL profesional y mágica.

REFERENCIA FOTOGRÁFICA:
- Foto adjunta del protagonista

TRANSFORMACIÓN ARTÍSTICA:
- Convierte al niño/a de la foto en un PERSONAJE ILUSTRADO estilo libro infantil moderno
- Mantén sus rasgos únicos identificables: {descripcion_fisica}
- Estilo: ilustración colorida y expresiva (NO fotorealista, NO foto editada)
- Referencias de estilo: Disney, Pixar, libros infantiles contemporáneos de alta calidad

HISTORIA:
- Título: "{titulo}"
- Tema: {tema}
- Mundo: {mundo_desc}
- Edad del lector: {age} años

COMPOSICIÓN:
- El protagonista ILUSTRADO en primer plano (60% de la imagen), en pose dinámica y expresiva
- Mundo fantástico coherente con "{tema}" de fondo
- Colores vibrantes, saturados y atractivos
- El título "{titulo}" integrado artísticamente en la composición
- Atmósfera mágica que invite a la aventura
- Detalles ricos que capturen la imaginación

ESTILO VISUAL:
- Ilustración digital profesional de alta calidad
- Paleta de colores alegre y fantástica
- Iluminación cinematográfica
- Textura y profundidad visual
- Aspecto de portada premium de librería

CRÍTICO: 
- El personaje debe ser una ILUSTRACIÓN COMPLETA basada en la foto, NO una foto editada o con filtros
- Debe parecer sacado de un libro de cuentos profesional
- El niño debe ser CLARAMENTE reconocible pero totalmente transformado en arte infantil"""

            print(f"📝 Generando portada ilustrada...")
            
            reference_image = Image.open(reference_photo_path)
            
            await self._respect_rate_limit()
            
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model='gemini-2.5-flash-image',
                contents=[prompt, reference_image],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio="1:1"
                    )
                )
            )
            
            # DEBUG: Ver qué responde Gemini
            print(f"🔍 DEBUG - Response type: {type(response)}")
            print(f"🔍 DEBUG - Response: {response}")
            if response:
                print(f"🔍 DEBUG - Parts: {response.parts if hasattr(response, 'parts') else 'No parts'}")
            
            # Validar y extraer
            if not response or not response.parts:
                print("❌ Respuesta vacía de Gemini")
                return None
            
            for part in response.parts:
                if part.inline_data is not None:
                    image_data = part.inline_data.data
                    
                    temp_filename = f"temp_cover_{secrets.token_urlsafe(8)}.png"
                    temp_path = settings.previews_dir / temp_filename
                    
                    async with aiofiles.open(temp_path, 'wb') as f:
                        await f.write(image_data)
                    
                    # Añadir texto con PIL
                    final_filename = await self._add_text_to_cover(
                        str(temp_path),
                        child_name
                    )
                    
                    # Borrar temporal
                    try:
                        temp_path.unlink(missing_ok=True)
                    except:
                        pass
                    
                    print(f"✅ Portada generada: {final_filename}")
                    return final_filename
            
            print("❌ No se pudo extraer portada")
            return None
            
        except Exception as e:
            print(f"❌ Error generando portada: {e}")
            return None
    
    async def generate_character_sheet(
        self, 
        story_data: Dict, 
        cover_image_path: str
    ) -> Optional[str]:
        """
        Genera sheet de personajes con IDs numéricos visibles
        Protagonista basado en portada, resto según descripciones
        """
        try:
            personajes = story_data.get('personajes_principales', [])
            objetos = story_data.get('objetos_importantes', [])
            
            # Construir prompt con IDs
            elementos_texto = []
            
            for p in personajes:
                if p['id'] == 1:
                    elementos_texto.append(f"ID {p['id']}: {p['nombre']} - {p['descripcion']} (BASADO FIELMENTE EN LA IMAGEN DE PORTADA)")
                else:
                    elementos_texto.append(f"ID {p['id']}: {p['nombre']} - {p['descripcion']}")
            
            for o in objetos:
                elementos_texto.append(f"ID {o['id']}: {o['nombre']} - {o['descripcion']}")
            
            elementos_str = "\n".join(elementos_texto)
            
            prompt = f"""Crea un MODEL SHEET / CHARACTER REFERENCE SHEET profesional.

ELEMENTOS:
{elementos_str}

FORMATO:
- Fondo blanco limpio
- Cada elemento bien separado horizontalmente
- Cada elemento tiene su NÚMERO ID visible DEBAJO (grande y claro)
- Estilo de ilustración infantil colorida y consistente
- Vista clara de cada personaje/objeto
- Como un "character design sheet" profesional

CRÍTICO: 
- El ID 1 (protagonista) debe basarse FIELMENTE en la portada adjunta
- Los demás elementos se generan según sus descripciones
- Cada número debe estar CLARAMENTE visible debajo de su elemento"""

            print(f"🎨 Generando character sheet...")
            
            cover_img = Image.open(cover_image_path)
            
            await self._respect_rate_limit()
            
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model='gemini-2.5-flash-image',
                contents=[prompt, cover_img],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio="16:9"
                    )
                )
            )
            
            # Validar y extraer
            if not response or not response.parts:
                print("❌ Respuesta vacía de Gemini")
                return None
            
            for part in response.parts:
                if part.inline_data is not None:
                    image_data = part.inline_data.data
                    
                    filename = f"char_sheet_{secrets.token_urlsafe(8)}.png"
                    file_path = settings.assets_dir / filename
                    
                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(image_data)
                    
                    print(f"✅ Character sheet generado: {filename}")
                    return filename
            
            print("❌ No se pudo extraer character sheet")
            return None
            
        except Exception as e:
            print(f"❌ Error generando character sheet: {e}")
            return None
    
    async def generate_scene_sheet(self, story_data: Dict) -> Optional[str]:
        """Genera sheet de escenarios con IDs numéricos"""
        try:
            escenarios = story_data.get('escenarios', [])
            
            escenarios_texto = []
            for e in escenarios:
                escenarios_texto.append(f"ID {e['id']}: {e['nombre']} - {e['descripcion']}")
            
            escenarios_str = "\n".join(escenarios_texto)
            
            prompt = f"""Crea un SCENE REFERENCE SHEET / BACKGROUND REFERENCE para un libro infantil.

ESCENARIOS:
{escenarios_str}

FORMATO:
- Cada escenario en un panel claramente dividido
- Cada escenario tiene su NÚMERO ID visible DEBAJO (grande y claro)
- Estilo de ilustración infantil colorida y consistente
- Vista clara de cada entorno
- Como un "location design sheet" profesional
- Fondos/ambientes sin personajes"""

            print(f"🎨 Generando scene sheet...")
            
            await self._respect_rate_limit()
            
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model='gemini-2.5-flash-image',
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio="16:9"
                    )
                )
            )
            
            # Validar y extraer
            if not response or not response.parts:
                print("❌ Respuesta vacía de Gemini")
                return None
            
            for part in response.parts:
                if part.inline_data is not None:
                    image_data = part.inline_data.data
                    
                    filename = f"scene_sheet_{secrets.token_urlsafe(8)}.png"
                    file_path = settings.assets_dir / filename
                    
                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(image_data)
                    
                    print(f"✅ Scene sheet generado: {filename}")
                    return filename
            
            print("❌ No se pudo extraer scene sheet")
            return None
            
        except Exception as e:
            print(f"❌ Error generando scene sheet: {e}")
            return None
    
    async def generate_page_image_with_retry(
        self, 
        page_data: Dict, 
        character_sheet_path: str, 
        scene_sheet_path: str, 
        max_retries: int = 3
    ) -> Optional[str]:
        """Genera imagen de página con sistema de retry"""
        for attempt in range(1, max_retries + 1):
            try:
                print(f"  Intento {attempt}/{max_retries}...")
                
                result = await self.generate_page_image(
                    page_data, 
                    character_sheet_path, 
                    scene_sheet_path
                )
                
                if result:
                    return result
                
                if attempt < max_retries:
                    print(f"  ⚠️ Reintentando en 2 segundos...")
                    await asyncio.sleep(2)
                    
            except Exception as e:
                print(f"  ❌ Intento {attempt} falló: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2)
        
        print(f"  ❌ Falló después de {max_retries} intentos")
        return None
    
    async def generate_page_image(
        self, 
        page_data: Dict, 
        character_sheet_path: str, 
        scene_sheet_path: str
    ) -> Optional[str]:
        """Genera imagen de página usando los sheets con IDs"""
        try:
            await self._respect_rate_limit()
            
            escena = page_data.get('escena_detallada', page_data.get('texto', ''))
            personajes_ids = page_data.get('personajes_ids', [])
            objetos_ids = page_data.get('objetos_ids', [])
            escenario_id = page_data.get('escenario_id')
            
            # Construir referencias por ID
            personajes_str = f"Personajes (usar IDs del sheet): {', '.join(map(str, personajes_ids))}. " if personajes_ids else ""
            objetos_str = f"Objetos (usar IDs del sheet): {', '.join(map(str, objetos_ids))}. " if objetos_ids else ""
            escenario_str = f"Escenario (usar ID del sheet): {escenario_id}. " if escenario_id else ""
            
            prompt = f"""REFERENCIAS:
- Primera imagen: character sheet con elementos numerados
- Segunda imagen: scene sheet con escenarios numerados

GENERA UNA ESCENA COMPLETAMENTE NUEVA:

Escena: {escena}
{personajes_str}{objetos_str}{escenario_str}

IMPORTANTE:
- Las imágenes son SOLO REFERENCIAS de elementos existentes
- Usa los elementos con los IDs especificados del sheet
- CREA una ilustración nueva basándote en las referencias
- Mantén el estilo visual consistente con los sheets
- Estilo infantil colorido
- Deja el 25% inferior con colores suaves (para texto después)
- SIN texto en la imagen
- Los IDs son los NÚMEROS que aparecen debajo de cada elemento en los sheets"""

            char_img = Image.open(character_sheet_path)
            scene_img = Image.open(scene_sheet_path)
            
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model='gemini-2.5-flash-image',
                contents=[prompt, char_img, scene_img],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio="1:1"
                    )
                )
            )
            
            # Validar y extraer
            if not response or not response.parts:
                print("❌ Respuesta vacía de Gemini")
                return None
            
            for part in response.parts:
                if part.inline_data is not None:
                    image_data = part.inline_data.data
                    filename = f"page_{secrets.token_urlsafe(8)}.png"
                    file_path = settings.books_dir / filename
                    
                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(image_data)
                    
                    return str(filename)
            
            print("❌ No se pudo extraer imagen")
            return None
            
        except Exception as e:
            print(f"❌ Error generando página: {e}")
            return None
    
    async def _add_text_to_cover(self, image_path: str, child_name: str) -> str:
        """Añadir texto abajo a la derecha SIN zona sombreada"""
        try:
            from PIL import Image as PILImage, ImageDraw, ImageFont
            
            img = PILImage.open(image_path)
            draw = ImageDraw.Draw(img)
            width, height = img.size
            
            # Fuente infantil
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
            except:
                font = ImageFont.load_default()
            
            # Texto
            text = f"Un libro para: {child_name}"
            
            # Calcular posición (abajo derecha con margen)
            text_bbox = draw.textbbox((0, 0), text, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            
            margin = 20
            text_x = width - text_width - margin
            text_y = height - text_height - margin
            
            # Dibujar texto en blanco
            draw.text((text_x, text_y), text, fill='white', font=font)
            
            # Guardar
            final_filename = f"cover_{secrets.token_urlsafe(8)}.png"
            final_path = settings.previews_dir / final_filename
            img.save(final_path)
            
            return final_filename
            
        except Exception as e:
            print(f"❌ Error añadiendo texto: {e}")
            from pathlib import Path
            return Path(image_path).name
    
    async def _respect_rate_limit(self):
        """Rate limiting"""
        now = time.time()
        time_since_last = now - self.last_request
        
        if time_since_last < self.min_delay:
            wait_time = self.min_delay - time_since_last
            await asyncio.sleep(wait_time)
        
        self.last_request = time.time()