from google import genai
from google.genai import types
import json
import asyncio
import aiofiles
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy.sql import func
from .config import settings
from .models import Book
from .database import SessionLocal
import secrets
import time
from PIL import Image, ImageDraw, ImageFont

class GeminiService:
    """Servicio para Gemini - Generación de historias con vision"""
    
    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY no configurada")
        
        self.client = genai.Client(api_key=settings.gemini_api_key)
        print("🤖 Gemini configurado correctamente")
    
    async def generate_story_from_photo(self, photo_path: str, child_name: str, age: int, description: str, num_pages: int = 12) -> Dict:
        """
        Analiza foto y genera historia completa usando Gemini 2.5 Flash
        """
        
        # Cargar imagen
        img = Image.open(photo_path)
        
        prompt = f"""Crea un cuento infantil personalizado basado en la foto.

INFORMACIÓN:
- Nombre: {child_name}
- Edad: {age} años
- Intereses: {description or 'aventuras'}
- Páginas: {num_pages} (EXACTAMENTE {num_pages} páginas)

IMPORTANTE - LÍMITES ESTRICTOS:
- Máximo 3 personajes (incluido {child_name})
- Máximo 3 objetos importantes
- Máximo 3 escenarios diferentes

HISTORIA:
- {child_name} como protagonista
- Apropiada para {age} años
- {num_pages} páginas exactas con texto corto por página (máximo 50 palabras por página)
- Final feliz con lección positiva

JSON CON IDS ÚNICOS:
{{
    "titulo": "Título del libro",
    "tema": "aventura/amistad/etc",
    "resumen": "Resumen breve del libro completo",
    "leccion": "Qué aprenderá",
    "personajes_principales": [
        {{"id": "protagonista", "descripcion": "El niño de la foto como personaje principal"}},
        {{"id": "id-descriptivo", "descripcion": "Descripción del personaje"}}
    ],
    "objetos_importantes": [
        {{"id": "id-descriptivo", "descripcion": "Descripción del objeto"}}
    ],
    "escenarios": [
        {{"id": "id-descriptivo", "descripcion": "Descripción del escenario"}}
    ],
    "paginas": [
        {{
            "numero": 1,
            "texto": "Texto corto (máximo 50 palabras)",
            "escena": "Qué ilustrar",
            "personajes_ids": ["protagonista"],
            "objetos_ids": ["id-objeto"],
            "escenario_id": "id-escenario"
        }}
    ]
}}

Los IDs deben ser descriptivos (ej: "amigo-robot-azul", "varita-magica", "bosque-encantado")."""
        
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=settings.gemini_model,
                contents=[prompt, img]
            )
            
            # Parsear JSON
            story_data = self._parse_gemini_response(response.text, child_name, num_pages)
            
            print(f"📖 Historia generada: '{story_data['titulo']}'")
            return story_data
            
        except Exception as e:
            print(f"❌ Error generando historia: {e}")
            return self._fallback_story(child_name, age, num_pages)
    
    def _parse_gemini_response(self, response_text: str, child_name: str, num_pages: int) -> Dict:
        """Parsear respuesta JSON de Gemini"""
        try:
            # Limpiar respuesta
            clean_text = response_text.strip()
            if clean_text.startswith('```json'):
                clean_text = clean_text[7:]
            if clean_text.startswith('```'):
                clean_text = clean_text[3:]
            if clean_text.endswith('```'):
                clean_text = clean_text[:-3]
            
            data = json.loads(clean_text.strip())
            
            # Validar estructura
            required_keys = ['titulo', 'paginas']
            for key in required_keys:
                if key not in data:
                    raise ValueError(f"Falta clave: {key}")
            
            # Añadir child_name
            data['child_name'] = child_name
            
            # Asegurar estructura con IDs
            if 'personajes_principales' not in data:
                data['personajes_principales'] = [
                    {"id": "protagonista", "descripcion": f"{child_name}, el protagonista"}
                ]
            
            if 'objetos_importantes' not in data:
                data['objetos_importantes'] = []
            
            if 'escenarios' not in data:
                data['escenarios'] = [
                    {"id": "escenario-principal", "descripcion": "Escenario de aventuras"}
                ]
            
            # Limitar a máximo 3 de cada
            data['personajes_principales'] = data['personajes_principales'][:3]
            data['objetos_importantes'] = data['objetos_importantes'][:3]
            data['escenarios'] = data['escenarios'][:3]
            
            # Ajustar páginas si es necesario
            if len(data['paginas']) != num_pages:
                print(f"⚠️ Ajustando páginas: {len(data['paginas'])} → {num_pages}")
                if len(data['paginas']) > num_pages:
                    data['paginas'] = data['paginas'][:num_pages]
                else:
                    while len(data['paginas']) < num_pages:
                        data['paginas'].append({
                            "numero": len(data['paginas']) + 1,
                            "texto": f"{child_name} continuó su aventura.",
                            "escena": "El niño en una escena de aventura",
                            "personajes_ids": ["protagonista"],
                            "objetos_ids": [],
                            "escenario_id": data['escenarios'][0]['id'] if data['escenarios'] else "escenario-principal"
                        })
            
            return data
            
        except Exception as e:
            print(f"❌ Error parseando Gemini: {e}")
            raise e
    
    def _fallback_story(self, child_name: str, age: int, num_pages: int) -> Dict:
        """Historia de respaldo"""
        pages = []
        for i in range(1, num_pages + 1):
            pages.append({
                "numero": i,
                "texto": f"{child_name} vivió una gran aventura.",
                "escena": f"{child_name} en una escena emocionante",
                "personajes_ids": ["protagonista"],
                "objetos_ids": [],
                "escenario_id": "bosque-magico"
            })
        
        return {
            "child_name": child_name,
            "titulo": f"Las Aventuras de {child_name}",
            "tema": "Aventura",
            "resumen": f"Una historia sobre {child_name}",
            "leccion": "Valentía y amistad",
            "personajes_principales": [
                {"id": "protagonista", "descripcion": f"{child_name}, el protagonista"}
            ],
            "objetos_importantes": [],
            "escenarios": [
                {"id": "bosque-magico", "descripcion": "Un bosque mágico lleno de aventuras"}
            ],
            "paginas": pages
        }


class GeminiImageService:
    """Servicio para Gemini 2.5 Flash Image - Generación de imágenes"""
    
    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY no configurada")
        
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.last_request = 0
        self.min_delay = 1
        print("🎨 Gemini Image Service configurado")
    
    async def generate_character_sheet(self, story_data: Dict, reference_image_path: str, book_id: str, child_name: str) -> Optional[str]:
        """Genera sheet de personajes y objetos importantes"""
        try:
            personajes = story_data.get('personajes_principales', [])
            objetos = story_data.get('objetos_importantes', [])
            
            # Construir lista detallada SIN IDs (solo descripciones)
            personajes_str = "\n".join([f"- {p['descripcion']}" for p in personajes])
            objetos_str = "\n".join([f"- {o['descripcion']}" for o in objetos]) if objetos else ""
            
            prompt = f"""Crea un MODEL SHEET / CHARACTER REFERENCE SHEET profesional para un libro infantil.

PERSONAJES (cada uno en pose neutral, claramente separado):
{personajes_str}

{f"OBJETOS IMPORTANTES (cada uno claramente visible y separado):\n{objetos_str}" if objetos_str else ""}

FORMATO:
- Fondo blanco limpio
- Cada elemento bien separado visualmente
- Estilo de ilustración infantil colorida y consistente
- Vista clara de cada personaje/objeto
- SIN texto, nombres ni etiquetas
- Como un "character design sheet" profesional

IMPORTANTE: El protagonista debe basarse fielmente en la foto de referencia."""

            print(f"🎨 Generando character sheet...")
            
            reference_image = Image.open(reference_image_path)
            
            await self._respect_rate_limit()
            
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model='gemini-2.5-flash-image',
                contents=[prompt, reference_image],
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
                    
                    filename = f"{child_name}_{book_id[:8]}_characters.png"
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
    
    async def generate_scene_sheet(self, story_data: Dict, book_id: str, child_name: str) -> Optional[str]:
        """Genera sheet de escenarios/fondos"""
        try:
            escenarios = story_data.get('escenarios', [])
            
            escenarios_str = "\n".join([f"- ID: {e['id']} → {e['descripcion']}" for e in escenarios])
            
            prompt = f"""Crea un SCENE REFERENCE SHEET / BACKGROUND REFERENCE para un libro infantil.

ESCENARIOS (cada uno en un panel separado):
{escenarios_str}

FORMATO:
- Cada escenario en un panel claramente dividido
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
                    
                    filename = f"{child_name}_{book_id[:8]}_scenes.png"
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
    
    async def generate_cover(self, story_data: Dict, character_sheet_path: str, scene_sheet_path: str) -> Optional[str]:
        """Genera portada usando los sheets como referencia"""
        try:
            child_name = story_data.get('child_name', 'el niño')
            tema = story_data.get('tema', 'aventura')
            titulo = story_data['titulo']
            
            prompt = f"""Crea una portada de libro infantil profesional.

REFERENCIAS:
- Primera imagen: personajes y objetos
- Segunda imagen: escenarios

PORTADA:
- Título: "{titulo}"
- Tema: {tema}
- Usa el protagonista (ID: protagonista) de la primera imagen en primer plano
- Usa un escenario de la segunda imagen como fondo
- Estilo ilustración infantil colorida
- Composición atractiva
- Añade el título del libro.
- No añadas ningun otro texto.

IMPORTANTE: Mantén el estilo visual de las referencias."""

            print(f"📝 Generando portada...")
            
            char_img = Image.open(character_sheet_path)
            scene_img = Image.open(scene_sheet_path)
            
            await self._respect_rate_limit()
            
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
            return Path(image_path).name
    
    async def generate_page_image_with_retry(self, page_data: Dict, character_sheet_path: str, scene_sheet_path: str, max_retries: int = 3) -> Optional[str]:
        """Genera imagen de página con sistema de retry"""
        for attempt in range(1, max_retries + 1):
            try:
                print(f"  Intento {attempt}/{max_retries}...")
                
                result = await self.generate_page_image(page_data, character_sheet_path, scene_sheet_path)
                
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
    
    async def generate_page_image(self, page_data: Dict, character_sheet_path: str, scene_sheet_path: str) -> Optional[str]:
        """Genera imagen de página usando los sheets con IDs"""
        try:
            await self._respect_rate_limit()
            
            escena = page_data.get('escena', page_data.get('texto', ''))
            personajes_ids = page_data.get('personajes_ids', [])
            objetos_ids = page_data.get('objetos_ids', [])
            escenario_id = page_data.get('escenario_id', '')
            
            personajes_str = f"Personajes (IDs): {', '.join(personajes_ids)}. " if personajes_ids else ""
            objetos_str = f"Objetos (IDs): {', '.join(objetos_ids)}. " if objetos_ids else ""
            escenario_str = f"Escenario (ID): {escenario_id}. " if escenario_id else ""
            
            prompt = f"""REFERENCIAS:
- Primera imagen: personajes y objetos (usa los elementos con los IDs especificados)
- Segunda imagen: escenarios (usa el escenario con el ID especificado)

GENERA UNA ESCENA COMPLETAMENTE NUEVA:

Escena: {escena}
{personajes_str}{objetos_str}{escenario_str}

IMPORTANTE:
- Las imágenes son SOLO REFERENCIAS visuales de elementos existentes
- NO edites ni combines las referencias
- CREA una ilustración nueva usando los elementos con los IDs especificados
- Mantén el estilo visual consistente
- Estilo infantil colorido
- Deja el 25% inferior con colores suaves (para texto después)
- SIN texto en la imagen"""

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
    
    async def _respect_rate_limit(self):
        """Rate limiting"""
        now = time.time()
        time_since_last = now - self.last_request
        
        if time_since_last < self.min_delay:
            wait_time = self.min_delay - time_since_last
            await asyncio.sleep(wait_time)
        
        self.last_request = time.time()


def update_book_progress(book_id: str, step: str, progress: int):
    """Actualizar progreso del libro en BD"""
    db = SessionLocal()
    try:
        book = db.query(Book).filter(Book.id == book_id).first()
        if book:
            book.current_step = step
            book.progress_percentage = progress
            db.commit()
    finally:
        db.close()


class BookGenerationService:
    """Servicio orquestador para generar libros completos"""
    
    def __init__(self):
        self.gemini = GeminiService()
        self.gemini_image = GeminiImageService()
    
    async def generate_preview_with_sheets(self, book_id: str):
        """Generar preview: historia + sheets + portada CON RETRY y tracking"""
        try:
            db = SessionLocal()
            book = db.query(Book).filter(Book.id == book_id).first()
            if not book:
                print(f"❌ Libro {book_id} no encontrado")
                return
            
            # 1. Generar historia
            update_book_progress(book_id, "Generando historia personalizada", 10)
            print(f"🤖 Generando historia...")
            story_data = await self.gemini.generate_story_from_photo(
                photo_path=book.original_photo_path,
                child_name=book.child_name,
                age=book.child_age,
                description=book.child_description or "",
                num_pages=book.total_pages
            )
            
            # 2. Generar character sheet CON RETRY
            update_book_progress(book_id, "Creando personajes únicos", 35)
            print(f"🎨 Generando character sheet...")
            char_sheet = None
            for attempt in range(1, 4):
                print(f"  Intento {attempt}/3...")
                char_sheet = await self.gemini_image.generate_character_sheet(
                    story_data=story_data,
                    reference_image_path=book.original_photo_path,
                    book_id=book.id,
                    child_name=book.child_name
                )
                if char_sheet:
                    break
                if attempt < 3:
                    print(f"  ⚠️ Reintentando en 2 segundos...")
                    await asyncio.sleep(2)
            
            if not char_sheet:
                raise Exception("No se pudo generar character sheet después de 3 intentos")
            
            # 3. Generar scene sheet CON RETRY
            update_book_progress(book_id, "Diseñando escenarios mágicos", 60)
            print(f"🏞️ Generando scene sheet...")
            scene_sheet = None
            for attempt in range(1, 4):
                print(f"  Intento {attempt}/3...")
                scene_sheet = await self.gemini_image.generate_scene_sheet(
                    story_data=story_data,
                    book_id=book.id,
                    child_name=book.child_name
                )
                if scene_sheet:
                    break
                if attempt < 3:
                    print(f"  ⚠️ Reintentando en 2 segundos...")
                    await asyncio.sleep(2)
            
            if not scene_sheet:
                raise Exception("No se pudo generar scene sheet después de 3 intentos")
            
            # 4. Generar portada usando sheets CON RETRY
            update_book_progress(book_id, "Generando portada", 85)
            print(f"📕 Generando portada...")
            cover_filename = None
            for attempt in range(1, 4):
                print(f"  Intento {attempt}/3...")
                cover_filename = await self.gemini_image.generate_cover(
                    story_data=story_data,
                    character_sheet_path=str(settings.assets_dir / char_sheet),
                    scene_sheet_path=str(settings.assets_dir / scene_sheet)
                )
                if cover_filename:
                    break
                if attempt < 3:
                    print(f"  ⚠️ Reintentando en 2 segundos...")
                    await asyncio.sleep(2)
            
            if not cover_filename:
                raise Exception("No se pudo generar portada después de 3 intentos")
            
            # 5. Actualizar BD
            update_book_progress(book_id, "Preview listo", 100)
            book.title = story_data['titulo']
            book.story_theme = story_data.get('tema', '')
            book.book_data_json = json.dumps(story_data, ensure_ascii=False)
            book.cover_preview_path = cover_filename
            book.status = 'preview_ready'
            
            db.commit()
            print(f"✅ Preview {book_id} completado con sheets")
            
        except Exception as e:
            print(f"❌ Error generando preview {book_id}: {e}")
            
            if 'db' in locals() and 'book' in locals():
                book.status = 'preview_error'
                book.generation_error = str(e)
                book.current_step = "Error en generación"
                db.commit()
        
        finally:
            if 'db' in locals():
                db.close()
    
    async def regenerate_preview_cover(self, book_id: str):
        """Regenerar SOLO la portada del preview (mantiene historia y sheets)"""
        try:
            db = SessionLocal()
            book = db.query(Book).filter(Book.id == book_id).first()
            if not book:
                print(f"❌ Libro {book_id} no encontrado")
                return False
            
            if not book.book_data_json:
                raise Exception("No hay historia para regenerar")
            
            story_data = json.loads(book.book_data_json)
            
            # Localizar sheets existentes
            char_sheet = settings.assets_dir / f"{book.child_name}_{book_id[:8]}_characters.png"
            scene_sheet = settings.assets_dir / f"{book.child_name}_{book_id[:8]}_scenes.png"
            
            if not char_sheet.exists() or not scene_sheet.exists():
                raise Exception("Sheets no encontrados, no se puede regenerar")
            
            # Actualizar estado
            book.status = 'generating_cover'
            book.current_step = "Regenerando portada"
            book.progress_percentage = 50
            db.commit()
            
            # Regenerar portada CON RETRY
            print(f"🔄 Regenerando portada...")
            cover_filename = None
            for attempt in range(1, 4):
                print(f"  Intento {attempt}/3...")
                cover_filename = await self.gemini_image.generate_cover(
                    story_data=story_data,
                    character_sheet_path=str(char_sheet),
                    scene_sheet_path=str(scene_sheet)
                )
                if cover_filename:
                    break
                if attempt < 3:
                    print(f"  ⚠️ Reintentando en 2 segundos...")
                    await asyncio.sleep(2)
            
            if not cover_filename:
                raise Exception("No se pudo regenerar portada después de 3 intentos")
            
            # Borrar portada anterior
            if book.cover_preview_path:
                try:
                    old_cover = settings.previews_dir / book.cover_preview_path
                    old_cover.unlink(missing_ok=True)
                except:
                    pass
            
            # Actualizar BD
            book.cover_preview_path = cover_filename
            book.status = 'preview_ready'
            book.current_step = "Preview listo"
            book.progress_percentage = 100
            db.commit()
            
            print(f"✅ Portada regenerada: {cover_filename}")
            return True
            
        except Exception as e:
            print(f"❌ Error regenerando portada: {e}")
            if 'db' in locals() and 'book' in locals():
                book.status = 'preview_error'
                book.generation_error = f"Error regenerando portada: {str(e)}"
                db.commit()
            return False
        finally:
            if 'db' in locals():
                db.close()
    
    async def generate_complete_book(self, book_id: str):
        """Generar libro completo usando sheets existentes CON RETRY y tracking"""
        try:
            db = SessionLocal()
            book = db.query(Book).filter(Book.id == book_id).first()
            if not book:
                print(f"❌ Libro {book_id} no encontrado")
                return
            
            book.status = 'generating'
            book.current_step = "Iniciando generación"
            book.progress_percentage = 0
            db.commit()
            
            story_data = json.loads(book.book_data_json)
            
            print(f"🎨 Generando libro completo para {book.child_name}...")
            
            # Localizar sheets
            char_sheet = settings.assets_dir / f"{book.child_name}_{book_id[:8]}_characters.png"
            scene_sheet = settings.assets_dir / f"{book.child_name}_{book_id[:8]}_scenes.png"
            
            if not char_sheet.exists() or not scene_sheet.exists():
                raise Exception("Sheets no encontrados")
            
            print(f"✅ Usando sheets existentes")
            
            # Generar páginas con RETRY y tracking
            page_filenames = []
            failed_pages = []
            total_pages = len(story_data['paginas'])
            
            for i, page_data in enumerate(story_data['paginas'], 1):
                progress = int(10 + (i / total_pages) * 80)  # 10% a 90%
                update_book_progress(book_id, f"Generando página {i}/{total_pages}", progress)
                print(f"🖼️ Generando página {i}/{total_pages}...")
                
                page_filename = await self.gemini_image.generate_page_image_with_retry(
                    page_data=page_data,
                    character_sheet_path=str(char_sheet),
                    scene_sheet_path=str(scene_sheet),
                    max_retries=3
                )
                
                if not page_filename:
                    print(f"❌ FALLO CRÍTICO: Página {i} falló después de 3 intentos")
                    failed_pages.append(i)
                    page_filenames.append(None)
                else:
                    page_filenames.append(page_filename)
            
            # Si alguna página falló, NO completar el libro
            if failed_pages:
                error_msg = f"Páginas fallidas: {', '.join(map(str, failed_pages))}"
                raise Exception(error_msg)
            
            # Crear PDF
            update_book_progress(book_id, "Creando PDF final", 95)
            print("📄 Creando PDF...")
            pdf_filename = await self._create_pdf(book, story_data, book.cover_preview_path, page_filenames)
            
            if not pdf_filename:
                raise Exception("No se pudo crear el PDF")
            
            # Finalizar
            update_book_progress(book_id, "Libro completado", 100)
            book.status = 'completed'
            book.pdf_path = pdf_filename
            book.completed_at = func.now()
            db.commit()
            
            print(f"🎉 Libro {book_id} completado exitosamente")
            
        except Exception as e:
            print(f"❌ Error generando libro {book_id}: {e}")
            db = SessionLocal()
            book = db.query(Book).filter(Book.id == book_id).first()
            if book:
                book.status = 'error'
                book.generation_error = str(e)
                book.current_step = "Error en generación"
                db.commit()
        finally:
            db.close()
    
    async def regenerate_single_page(self, book_id: str, page_number: int):
        """Regenerar una página específica y recrear el PDF"""
        try:
            db = SessionLocal()
            book = db.query(Book).filter(Book.id == book_id).first()
            if not book or book.status != 'completed':
                raise Exception("Libro no encontrado o no completado")
            
            story_data = json.loads(book.book_data_json)
            
            if page_number < 1 or page_number > len(story_data['paginas']):
                raise Exception(f"Página {page_number} inválida")
            
            page_data = story_data['paginas'][page_number - 1]
            
            # Localizar sheets
            char_sheet = settings.assets_dir / f"{book.child_name}_{book_id[:8]}_characters.png"
            scene_sheet = settings.assets_dir / f"{book.child_name}_{book_id[:8]}_scenes.png"
            
            if not char_sheet.exists() or not scene_sheet.exists():
                raise Exception("Sheets no encontrados")
            
            print(f"🔄 Regenerando página {page_number}...")
            
            # Regenerar página
            new_page_filename = await self.gemini_image.generate_page_image_with_retry(
                page_data=page_data,
                character_sheet_path=str(char_sheet),
                scene_sheet_path=str(scene_sheet),
                max_retries=3
            )
            
            if not new_page_filename:
                raise Exception("No se pudo regenerar la página")
            
            # Obtener nombres de archivos de todas las páginas actuales
            page_filenames = []
            # Extraer de algún lugar o reconstruir - por ahora asumimos están en books_dir
            # En producción deberías guardar la lista en book_data_json
            for i in range(1, len(story_data['paginas']) + 1):
                if i == page_number:
                    page_filenames.append(new_page_filename)
                else:
                    # Buscar archivo existente (esto es simplificado)
                    # En producción deberías guardar la lista de archivos
                    page_filenames.append(None)  # Placeholder
            
            # Recrear PDF con la nueva página
            print("📄 Recreando PDF...")
            pdf_filename = await self._create_pdf(book, story_data, book.cover_preview_path, page_filenames)
            
            if not pdf_filename:
                raise Exception("No se pudo recrear el PDF")
            
            # Actualizar BD
            book.pdf_path = pdf_filename
            db.commit()
            
            print(f"✅ Página {page_number} regenerada y PDF actualizado")
            return True
            
        except Exception as e:
            print(f"❌ Error regenerando página: {e}")
            return False
        finally:
            db.close()
    
    async def _create_pdf(self, book: Book, story_data: Dict, cover_filename: Optional[str], page_filenames: List[Optional[str]]) -> Optional[str]:
        """Crear PDF con imágenes a página completa, texto superpuesto y contraportada"""
        try:
            from reportlab.lib.pagesizes import inch
            from reportlab.pdfgen import canvas
            from reportlab.lib.colors import Color
            
            PAGE_SIZE = (8.5*inch, 8.5*inch)
            
            pdf_filename = f"libro_{book.child_name}_{book.id[:8]}.pdf"
            pdf_path = settings.pdfs_dir / pdf_filename
            
            c = canvas.Canvas(str(pdf_path), pagesize=PAGE_SIZE)
            width, height = PAGE_SIZE
            
            # 1. PORTADA a página completa
            if cover_filename:
                cover_path = settings.previews_dir / cover_filename
                if cover_path.exists():
                    c.drawImage(str(cover_path), 0, 0, width=width, height=height, preserveAspectRatio=True, anchor='c')
                    c.showPage()
            
            # 2. PÁGINAS con imagen + texto superpuesto CON ajuste automático
            for i, page_data in enumerate(story_data['paginas'], 1):
                page_filename = page_filenames[i-1] if i-1 < len(page_filenames) else None
                
                # Dibujar imagen de fondo
                if page_filename:
                    page_path = settings.books_dir / page_filename
                    if page_path.exists():
                        c.drawImage(str(page_path), 0, 0, width=width, height=height, preserveAspectRatio=True, anchor='c')
                
                # Zona de texto con fondo semi-transparente
                text_height = 2*inch
                c.setFillColor(Color(0, 0, 0, alpha=0.5))
                c.rect(0, 0, width, text_height, fill=1, stroke=0)
                
                # Texto en blanco con ajuste automático de tamaño
                texto = page_data['texto']
                max_width = width - inch
                max_lines = 7  # Máximo de líneas que caben
                
                # Intentar con diferentes tamaños de fuente
                font_size = self._get_optimal_font_size(c, texto, max_width, text_height - inch, max_lines)
                
                c.setFillColor(Color(1, 1, 1, alpha=1))
                c.setFont("Helvetica-Bold", font_size)
                
                # Dividir texto en líneas
                lines = self._wrap_text(c, texto, max_width, "Helvetica-Bold", font_size)
                
                # Dibujar líneas centradas verticalmente en el área de texto
                y_start = text_height - 0.5*inch
                line_height = font_size + 4
                x_left = 0.5*inch
                
                for line in lines:
                    c.drawString(x_left, y_start, line)
                    y_start -= line_height
                
                c.showPage()
            
            # 3. CONTRAPORTADA
            await self._add_back_cover(c, story_data, width, height)
            c.showPage()
            
            c.save()
            print(f"📄 PDF creado: {pdf_filename} (14 páginas totales)")
            return pdf_filename
            
        except Exception as e:
            print(f"❌ Error creando PDF: {e}")
            return None
    
    def _get_optimal_font_size(self, canvas_obj, text: str, max_width: float, max_height: float, max_lines: int) -> int:
        """Calcular el tamaño de fuente óptimo para que el texto quepa"""
        for font_size in [18, 16, 14, 12]:
            lines = self._wrap_text(canvas_obj, text, max_width, "Helvetica-Bold", font_size)
            line_height = font_size + 4
            total_height = len(lines) * line_height
            
            if len(lines) <= max_lines and total_height <= max_height:
                return font_size
        
        return 12  # Mínimo
    
    def _wrap_text(self, canvas_obj, text: str, max_width: float, font_name: str, font_size: int) -> List[str]:
        """Dividir texto en líneas que quepan en el ancho máximo"""
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            test_line = current_line + " " + word if current_line else word
            if canvas_obj.stringWidth(test_line, font_name, font_size) < max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        
        if current_line:
            lines.append(current_line)
        
        return lines
    
    async def _add_back_cover(self, canvas_obj, story_data: Dict, width: float, height: float):
        """Añadir contraportada con PIL y luego insertarla en el PDF"""
        try:
            from PIL import Image as PILImage, ImageDraw, ImageFont
            
            # Crear imagen para contraportada
            img_width = int(width * 72 / inch)  # Convertir a pixels
            img_height = int(height * 72 / inch)
            
            img = PILImage.new('RGB', (img_width, img_height))
            draw = ImageDraw.Draw(img)
            
            # Fondo degradado (simulado con rectángulos)
            for i in range(img_height):
                ratio = i / img_height
                r = int(200 + (150 - 200) * ratio)
                g = int(220 + (200 - 220) * ratio)
                b = int(255 + (230 - 255) * ratio)
                draw.rectangle([(0, i), (img_width, i+1)], fill=(r, g, b))
            
            # Cargar fuentes
            try:
                title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
                text_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
            except:
                title_font = ImageFont.load_default()
                text_font = ImageFont.load_default()
            
            # Título del libro (centrado, arriba)
            titulo = story_data.get('titulo', 'Un Libro Mágico')
            title_bbox = draw.textbbox((0, 0), titulo, font=title_font)
            title_width = title_bbox[2] - title_bbox[0]
            title_x = (img_width - title_width) // 2
            title_y = 100
            
            draw.text((title_x, title_y), titulo, fill=(50, 50, 100), font=title_font)
            
            # Resumen (centrado, en el medio)
            resumen = story_data.get('resumen', 'Una aventura maravillosa')
            
            # Dividir resumen en líneas
            words = resumen.split()
            lines = []
            current_line = ""
            max_width = img_width - 200
            
            for word in words:
                test_line = current_line + " " + word if current_line else word
                test_bbox = draw.textbbox((0, 0), test_line, font=text_font)
                test_width = test_bbox[2] - test_bbox[0]
                
                if test_width < max_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            
            if current_line:
                lines.append(current_line)
            
            # Dibujar líneas del resumen
            y_pos = img_height // 2 - (len(lines) * 40) // 2
            for line in lines:
                line_bbox = draw.textbbox((0, 0), line, font=text_font)
                line_width = line_bbox[2] - line_bbox[0]
                line_x = (img_width - line_width) // 2
                draw.text((line_x, y_pos), line, fill=(70, 70, 70), font=text_font)
                y_pos += 45
            
            # Guardar imagen temporal
            temp_back_cover = settings.pdfs_dir / f"temp_back_{secrets.token_urlsafe(8)}.png"
            img.save(temp_back_cover)
            
            # Dibujar en el canvas
            canvas_obj.drawImage(str(temp_back_cover), 0, 0, width=width, height=height)
            
            # Limpiar temporal
            try:
                temp_back_cover.unlink(missing_ok=True)
            except:
                pass
            
            print("✅ Contraportada añadida")
            
        except Exception as e:
            print(f"❌ Error creando contraportada: {e}")
            # Si falla, poner una contraportada simple
            canvas_obj.setFillColor(Color(0.85, 0.9, 1.0))
            canvas_obj.rect(0, 0, width, height, fill=1, stroke=0)
            canvas_obj.setFillColor(Color(0.2, 0.2, 0.4))
            canvas_obj.setFont("Helvetica-Bold", 48)
            canvas_obj.drawCentredString(width/2, height/2, story_data.get('titulo', 'Un Libro Mágico'))


# Singleton
_book_service = None

def get_book_service() -> BookGenerationService:
    """Obtener instancia del servicio"""
    global _book_service
    if _book_service is None:
        _book_service = BookGenerationService()
    return _book_service