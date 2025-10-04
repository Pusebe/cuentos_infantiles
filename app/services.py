import google.generativeai as genai
import json
import asyncio
import aiohttp
import aiofiles
import base64
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from .config import settings
from .models import Book
from .database import SessionLocal
import secrets
import time
from PIL import Image

class GeminiService:
    """Servicio para Gemini - Generación de historias con vision"""
    
    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY no configurada")
        
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel(settings.gemini_model)
        print("🤖 Gemini configurado correctamente")
    
    async def generate_story_from_photo(self, photo_path: str, child_name: str, age: int, description: str, num_pages: int) -> Dict:
        """
        Analiza foto y genera historia completa usando Gemini 2.5 Flash
        """
        
        # Cargar imagen
        img = Image.open(photo_path)
        
        prompt = f"""
        Analiza esta foto y crea un cuento infantil personalizado.

        INFORMACIÓN:
        - Nombre del niño: {child_name}
        - Edad: {age} años
        - Descripción adicional: {description or 'Le gustan las aventuras'}
        - Páginas del libro: {num_pages}

        ANÁLISIS DE LA FOTO:
        1. Describe detalladamente la apariencia del niño (pelo, ojos, ropa, expresión)
        2. Identifica elementos del fondo que puedan inspirar la historia
        3. Nota el contexto y ambiente de la foto

        REQUISITOS DE LA HISTORIA:
        - Adaptada perfectamente para un niño de {age} años
        - {child_name} como protagonista heroico
        - {num_pages} páginas exactas
        - Cada página: 1-2 frases cortas (ideales para ilustrar)
        - Historia emocionante que los padres quieran comprar
        - Final feliz con lección positiva

        RESPONDE EN FORMATO JSON EXACTO:
        {{
            "child_description": "Descripción física detallada del niño de la foto",
            "scene_context": "Descripción del fondo y ambiente de la foto",
            "titulo": "Título atractivo del libro",
            "tema": "Tema principal (aventura, amistad, etc)",
            "resumen": "Resumen de 1 frase",
            "leccion": "Qué aprenderá el niño",
            "paginas": [
                {{"numero": 1, "texto": "Texto de la página 1", "escena": "Descripción de qué ilustrar"}},
                {{"numero": 2, "texto": "Texto de la página 2", "escena": "Descripción de qué ilustrar"}},
                ... hasta {num_pages} páginas
            ]
        }}
        """
        
        try:
            response = await asyncio.to_thread(
                self.model.generate_content,
                [prompt, img]
            )
            
            # Parsear JSON
            story_data = self._parse_gemini_response(response.text, child_name, num_pages)
            
            print(f"📖 Historia generada con Gemini: '{story_data['titulo']}'")
            return story_data
            
        except Exception as e:
            print(f"❌ Error generando historia con Gemini: {e}")
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
            required_keys = ['child_description', 'titulo', 'paginas']
            for key in required_keys:
                if key not in data:
                    raise ValueError(f"Falta clave: {key}")
            
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
                            "escena": "El niño en una escena de aventura"
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
                "escena": f"{child_name} en una escena emocionante"
            })
        
        return {
            "child_description": f"Niño de {age} años llamado {child_name}",
            "scene_context": "Ambiente de aventura",
            "titulo": f"Las Aventuras de {child_name}",
            "tema": "Aventura",
            "resumen": f"Una historia sobre {child_name}",
            "leccion": "Valentía y amistad",
            "paginas": pages
        }


class IdeogramService:
    """Servicio para Ideogram - Generación de imágenes con character reference"""
    
    def __init__(self):
        if not settings.ideogram_api_key:
            raise ValueError("IDEOGRAM_API_KEY no configurada")
        
        self.api_key = settings.ideogram_api_key
        self.base_url = "https://api.ideogram.ai/v1/ideogram-v3/generate"
        self.last_request = 0
        self.min_delay = 2  # Rate limiting
        print("🎨 Ideogram configurado correctamente")
    
    async def generate_cover(self, story_data: Dict, reference_image_path: str) -> Optional[str]:
        """
        Genera portada usando la foto del niño como character reference
        """
        try:
            await self._respect_rate_limit()
            
            child_desc = story_data.get('child_description', 'un niño')
            
            prompt = f"""
            Portada profesional de libro infantil.
            
            TÍTULO: "{story_data['titulo']}" - texto grande, claro y perfectamente legible
            SUBTÍTULO: "Un cuento para [nombre del niño]"
            
            PERSONAJE PRINCIPAL: {child_desc}
            TEMA: {story_data.get('tema', 'aventura')}
            
            ESTILO: Ilustración Disney/Pixar de alta calidad, colores vibrantes,
            diseño comercial que destaque en estanterías. El texto del título debe
            ser perfecto sin errores. Portada que vale 10€.
            """
            
            image_url = await self._generate_with_character_reference(
                prompt,
                reference_image_path
            )
            
            if image_url:
                filename = f"cover_{secrets.token_urlsafe(8)}.png"
                file_path = settings.previews_dir / filename
                
                if await self._download_image(image_url, file_path):
                    print(f"✅ Portada generada: {filename}")
                    return str(filename)
            
            return None
            
        except Exception as e:
            print(f"❌ Error generando portada: {e}")
            return None
    
    async def generate_page(self, page_data: Dict, story_data: Dict, reference_image_path: str, page_number: int) -> Optional[str]:
        """
        Genera página usando imagen anterior como referencia
        """
        try:
            await self._respect_rate_limit()
            
            child_desc = story_data.get('child_description', 'un niño')
            
            prompt = f"""
            Ilustración página {page_number} de libro infantil.
            
            ESCENA: {page_data.get('escena', page_data['texto'])}
            PERSONAJE: {child_desc} (debe ser consistente con la referencia)
            TEMA: {story_data.get('tema', 'aventura')}
            
            ESTILO: Ilustración Disney/Pixar, colores vibrantes, apropiada para niños.
            El personaje debe ser reconocible y consistente.
            SIN TEXTO en la imagen.
            """
            
            image_url = await self._generate_with_character_reference(
                prompt,
                reference_image_path
            )
            
            if image_url:
                filename = f"page_{page_number:02d}_{secrets.token_urlsafe(8)}.png"
                file_path = settings.books_dir / filename
                
                if await self._download_image(image_url, file_path):
                    print(f"✅ Página {page_number} generada: {filename}")
                    return str(filename)
            
            return None
            
        except Exception as e:
            print(f"❌ Error generando página {page_number}: {e}")
            return None
    
    async def _generate_with_character_reference(self, prompt: str, reference_image_path: str) -> Optional[str]:
        """
        Genera imagen usando Ideogram con character reference
        """
        try:
            # Leer imagen de referencia
            with open(reference_image_path, 'rb') as f:
                image_data = f.read()
            
            # Preparar request multipart
            form_data = aiohttp.FormData()
            form_data.add_field('prompt', prompt)
            form_data.add_field('model', settings.ideogram_model)
            form_data.add_field('magic_prompt', str(settings.ideogram_magic_prompt).lower())
            form_data.add_field('aspect_ratio', settings.ideogram_aspect_ratio)
            form_data.add_field('character_reference_images', image_data, 
                              filename='reference.jpg',
                              content_type='image/jpeg')
            
            headers = {
                'Api-Key': self.api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.base_url, data=form_data, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        
                        # Extraer URL de la imagen generada
                        if 'data' in result and len(result['data']) > 0:
                            return result['data'][0]['url']
                    else:
                        error_text = await response.text()
                        print(f"❌ Ideogram error {response.status}: {error_text}")
                        return None
            
        except Exception as e:
            print(f"❌ Error en Ideogram API: {e}")
            return None
    
    async def _download_image(self, url: str, save_path: Path) -> bool:
        """Descargar imagen de URL"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.read()
                        async with aiofiles.open(save_path, 'wb') as f:
                            await f.write(content)
                        return True
            return False
        except Exception as e:
            print(f"❌ Error descargando imagen: {e}")
            return False
    
    async def _respect_rate_limit(self):
        """Rate limiting"""
        now = time.time()
        time_since_last = now - self.last_request
        
        if time_since_last < self.min_delay:
            wait_time = self.min_delay - time_since_last
            await asyncio.sleep(wait_time)
        
        self.last_request = time.time()


class BookGenerationService:
    """Servicio orquestador para generar libros completos"""
    
    def __init__(self):
        self.gemini = GeminiService()
        self.ideogram = IdeogramService()
    
    async def generate_complete_book(self, book_id: str):
        """
        Generar libro completo: portada + todas las páginas + PDF
        """
        try:
            db = SessionLocal()
            book = db.query(Book).filter(Book.id == book_id).first()
            if not book:
                print(f"❌ Libro {book_id} no encontrado")
                return
            
            book.status = 'generating'
            db.commit()
            
            story_data = json.loads(book.book_data_json)
            
            print(f"🎨 Generando libro completo para {book.child_name}...")
            
            # 1. Generar portada (usando foto original como referencia)
            print("📖 Generando portada con Ideogram...")
            cover_filename = await self.ideogram.generate_cover(
                story_data,
                book.original_photo_path
            )
            
            # 2. Generar todas las páginas (cada una usando la anterior como referencia)
            page_filenames = []
            previous_image = book.original_photo_path  # Primera página usa foto original
            
            if cover_filename:
                previous_image = str(settings.previews_dir / cover_filename)  # Luego usa portada
            
            for i, page_data in enumerate(story_data['paginas'], 1):
                print(f"🖼️ Generando página {i}/{len(story_data['paginas'])}...")
                
                page_filename = await self.ideogram.generate_page(
                    page_data,
                    story_data,
                    previous_image,
                    i
                )
                
                page_filenames.append(page_filename)
                
                # Actualizar referencia para siguiente página
                if page_filename:
                    previous_image = str(settings.books_dir / page_filename)
            
            # 3. Crear PDF
            print("📄 Creando PDF...")
            pdf_filename = await self._create_pdf(book, story_data, cover_filename, page_filenames)
            
            # 4. Finalizar
            book.status = 'completed'
            book.pdf_path = pdf_filename
            book.completed_at = func.now()
            db.commit()
            
            print(f"🎉 Libro {book_id} completado")
            
        except Exception as e:
            print(f"❌ Error generando libro {book_id}: {e}")
            db = SessionLocal()
            book = db.query(Book).filter(Book.id == book_id).first()
            if book:
                book.status = 'error'
                book.generation_error = str(e)
                db.commit()
        finally:
            db.close()
    
    async def _create_pdf(self, book: Book, story_data: Dict, cover_filename: Optional[str], page_filenames: List[Optional[str]]) -> Optional[str]:
        """Crear PDF final"""
        try:
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.lib.colors import darkblue, black
            from reportlab.lib.enums import TA_CENTER
            
            pdf_filename = f"libro_{book.child_name}_{book.id[:8]}.pdf"
            pdf_path = settings.pdfs_dir / pdf_filename
            
            doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
            story = []
            styles = getSampleStyleSheet()
            
            title_style = ParagraphStyle(
                'Title',
                parent=styles['Title'],
                fontSize=28,
                textColor=darkblue,
                alignment=TA_CENTER,
                fontName='Helvetica-Bold'
            )
            
            text_style = ParagraphStyle(
                'Text',
                parent=styles['Normal'],
                fontSize=16,
                textColor=black,
                alignment=TA_CENTER,
                leading=22
            )
            
            # Título
            story.append(Paragraph(story_data['titulo'], title_style))
            story.append(Spacer(1, 0.5*inch))
            
            # Portada
            if cover_filename:
                cover_path = settings.previews_dir / cover_filename
                if cover_path.exists():
                    img = RLImage(str(cover_path))
                    img.drawHeight = 6*inch
                    img.drawWidth = 6*inch
                    story.append(img)
            
            story.append(Spacer(1, 1*inch))
            
            # Páginas
            for i, page_data in enumerate(story_data['paginas'], 1):
                page_filename = page_filenames[i-1] if i-1 < len(page_filenames) else None
                
                if page_filename:
                    page_path = settings.books_dir / page_filename
                    if page_path.exists():
                        img = RLImage(str(page_path))
                        img.drawHeight = 5.5*inch
                        img.drawWidth = 5.5*inch
                        story.append(img)
                        story.append(Spacer(1, 0.3*inch))
                
                story.append(Paragraph(page_data['texto'], text_style))
                story.append(Spacer(1, 1*inch))
            
            doc.build(story)
            print(f"📄 PDF creado: {pdf_filename}")
            return pdf_filename
            
        except Exception as e:
            print(f"❌ Error creando PDF: {e}")
            return None


# Singleton
_book_service = None

def get_book_service() -> BookGenerationService:
    """Obtener instancia del servicio"""
    global _book_service
    if _book_service is None:
        _book_service = BookGenerationService()
    return _book_service