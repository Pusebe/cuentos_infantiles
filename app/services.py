import openai
import json
import asyncio
import base64
import aiohttp
import aiofiles
from pathlib import Path
from PIL import Image
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from .config import settings
from .models import Book
from .database import SessionLocal
import secrets
import time

class OpenAIService:
    def __init__(self):
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY no configurada")
        
        try:
            # Inicialización simple sin argumentos problemáticos
            import openai
            self.client = openai.OpenAI(api_key=settings.openai_api_key)
            print("🤖 OpenAI Client configurado correctamente")
        except Exception as e:
            print(f"❌ Error configurando OpenAI Client: {e}")
            # Fallback para versiones más antiguas
            import openai
            openai.api_key = settings.openai_api_key
            self.client = openai  # Usar el módulo directamente
            print("🔄 Usando configuración OpenAI legacy")
        
        # Rate limiting para evitar 429 errors
        self.last_image_request = 0
        self.min_delay_between_images = 12  # 5 img/min = 12s between requests
    
    async def generate_story(self, child_name: str, age: int, description: str, num_pages: int) -> Dict:
        """
        Generar historia apropiada para la edad con GPT-5
        """
        age_guidance = {
            range(1, 4): "Muy simple, frases cortas, conceptos básicos como colores y formas",
            range(4, 7): "Simple pero con pequeñas aventuras, aprendizaje de valores",
            range(7, 10): "Aventuras más elaboradas, resolución de problemas sencillos",
            range(10, 13): "Historias complejas, desarrollo de personajes, moralejas profundas"
        }
        
        guidance = "Aventura apropiada para la edad"
        for age_range, text in age_guidance.items():
            if age in age_range:
                guidance = text
                break
        
        prompt = f"""
        Crea un cuento infantil personalizado para {child_name} de {age} años.
        
        INFORMACIÓN DEL NIÑO:
        - Nombre: {child_name}
        - Edad: {age} años
        - Descripción: {description or 'Le gustan las aventuras'}
        
        REQUISITOS:
        - {guidance}
        - Historia positiva, educativa y apropiada para {age} años
        - {num_pages} páginas de contenido
        - Cada página debe tener 1-2 frases máximo (apropiado para ilustrar)
        - Incluye a {child_name} como protagonista
        - Final feliz y educativo
        
        RESPONDE EN FORMATO JSON EXACTO:
        {{
            "titulo": "Título atractivo del libro",
            "tema": "Tema principal (aventura, amistad, etc)",
            "resumen": "Breve resumen de 1 frase",
            "paginas": [
                {{"numero": 1, "texto": "Primera frase de la historia."}},
                {{"numero": 2, "texto": "Segunda parte de la aventura."}},
                ...hasta página {num_pages}
            ]
        }}
        """
        
        try:
            response = await self._call_gpt5(prompt)
            story_data = self._parse_story_response(response, child_name, num_pages)
            
            print(f"📖 Historia generada: '{story_data['titulo']}' - {len(story_data['paginas'])} páginas")
            return story_data
            
        except Exception as e:
            print(f"❌ Error generando historia: {e}")
            return self._fallback_story(child_name, age, num_pages)
    
    async def generate_cover_preview(self, child_name: str, age: int, photo_path: str, story_data: Dict) -> Optional[str]:
        """
        Generar portada de preview gratuito (calidad baja con marca de agua)
        """
        try:
            # Esperar rate limit
            await self._respect_rate_limit()
            
            # Prompt específico para portada
            prompt = f"""
            Portada de libro infantil con el niño protagonista. Fondo colorido y relacionado con el tema: {story_data['tema']}.
            Texto principal: "{story_data['titulo']}", centrado en la parte superior, letras grandes, legibles, tipografía infantil sans-serif, estilo amigable y brillante.
            Subtítulo: "Un cuento para {child_name}", justo debajo del título, mismo estilo, color que contraste con el fondo.
            El niño protagonista debe ser reconocible y en estilo ilustración infantil profesional, colores brillantes y alegres.
            """
            
            # Generar imagen con referencia a la foto
            image_url = await self._generate_gpt_image(prompt, photo_path, quality="standard")
            
            if image_url:
                # Descargar y guardar imagen
                preview_filename = f"cover_preview_{child_name}_{secrets.token_urlsafe(8)}.png"
                preview_path = settings.previews_dir / preview_filename
                
                if await self._download_and_save_image(image_url, preview_path):
                    print(f"✅ Portada preview generada: {preview_filename}")
                    return str(preview_filename)
            
            return None
            
        except Exception as e:
            print(f"❌ Error generando portada preview: {e}")
            return None
    
    async def generate_complete_book(self, book_id: str):
        """
        Generar libro completo (portada + todas las páginas)
        Proceso asíncrono que actualiza el estado en BD
        """
        try:
            # Obtener datos del libro
            db = SessionLocal()
            book = db.query(Book).filter(Book.id == book_id).first()
            if not book:
                print(f"❌ Libro {book_id} no encontrado")
                return
            
            # Actualizar estado
            book.status = 'generating'
            db.commit()
            
            # Parsear datos de la historia
            story_data = json.loads(book.book_data_json)
            
            print(f"🎨 Generando libro completo para {book.child_name}...")
            
            # 1. Generar portada final (sin marca de agua)
            print("📖 Generando portada final...")
            cover_path = await self._generate_final_cover(book, story_data)
            
            # 2. Generar todas las páginas
            page_paths = []
            for i, page_data in enumerate(story_data['paginas'], 1):
                print(f"🖼️ Generando página {i}/{len(story_data['paginas'])}...")
                
                page_path = await self._generate_page_image(book, page_data, i)
                page_paths.append(page_path)
                
                # Esperar entre requests para respetar rate limit
                if i < len(story_data['paginas']):
                    await asyncio.sleep(self.min_delay_between_images)
            
            # 3. Generar PDF final
            print("📄 Generando PDF...")
            pdf_path = await self._create_final_pdf(book, story_data, cover_path, page_paths)
            
            # 4. Actualizar estado final
            book.status = 'completed'
            book.pdf_path = str(pdf_path) if pdf_path else None
            book.completed_at = func.now()
            db.commit()
            
            print(f"🎉 Libro {book_id} completado exitosamente")
            
            # TODO: Enviar email de notificación
            
        except Exception as e:
            print(f"❌ Error generando libro completo {book_id}: {e}")
            
            # Actualizar estado de error
            db = SessionLocal()
            book = db.query(Book).filter(Book.id == book_id).first()
            if book:
                book.status = 'error'
                book.generation_error = str(e)
                db.commit()
        
        finally:
            db.close()
    
    async def _call_gpt5(self, prompt: str) -> str:
        """Llamada a GPT-5 nano con la nueva API (sin max_tokens deprecado)"""
        try:
            response = self.client.chat.completions.create(
                model=settings.openai_model,  # gpt-5-nano
                messages=[
                    {"role": "system", "content": "Eres un experto escritor de cuentos infantiles. Respondes siempre en JSON válido."},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=1500,  # CORRECTO: max_completion_tokens en lugar de max_tokens
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            print(f"❌ Error llamando {settings.openai_model}: {e}")
            raise e
    
    async def _generate_gpt_image(self, prompt: str, reference_photo_path: str = None, quality: str = "standard") -> Optional[str]:
        """Generar imagen con DALL-E 3 (más estable que gpt-image-1)"""
        try:
            # Respectar rate limiting
            await self._respect_rate_limit()
            
            # Usar DALL-E 3 que es más estable
            response = self.client.images.generate(
                model="dall-e-3",  # DALL-E 3 en lugar de gpt-image-1
                prompt=prompt,
                size=settings.openai_image_size,
                quality=quality,  # standard o hd
                n=1
            )
            
            return response.data[0].url
            
        except Exception as e:
            print(f"❌ Error generando imagen con DALL-E 3: {e}")
            if "billing" in str(e).lower() or "quota" in str(e).lower():
                print("💳 Problema de cuota/billing de OpenAI")
            return None
    
    async def _respect_rate_limit(self):
        """Esperar el tiempo necesario para respetar rate limit"""
        now = time.time()
        time_since_last = now - self.last_image_request
        
        if time_since_last < self.min_delay_between_images:
            wait_time = self.min_delay_between_images - time_since_last
            print(f"⏳ Esperando {wait_time:.1f}s para respetar rate limit...")
            await asyncio.sleep(wait_time)
        
        self.last_image_request = time.time()
    
    def _parse_story_response(self, response: str, child_name: str, num_pages: int) -> Dict:
        """Parsear respuesta de GPT y validar"""
        try:
            # Limpiar markdown si existe
            clean_response = response.strip()
            if clean_response.startswith('```json'):
                clean_response = clean_response[7:]
            if clean_response.startswith('```'):
                clean_response = clean_response[3:]
            if clean_response.endswith('```'):
                clean_response = clean_response[:-3]
            
            story_data = json.loads(clean_response.strip())
            
            # Validar estructura
            required_keys = ['titulo', 'tema', 'paginas']
            for key in required_keys:
                if key not in story_data:
                    raise ValueError(f"Falta clave: {key}")
            
            if len(story_data['paginas']) != num_pages:
                raise ValueError(f"Número incorrecto de páginas: {len(story_data['paginas'])}")
            
            return story_data
            
        except Exception as e:
            print(f"❌ Error parseando historia: {e}")
    async def _generate_final_cover(self, book: Book, story_data: Dict) -> Optional[str]:
        """
        Generar portada final (sin marca de agua)
        """
        try:
            await self._respect_rate_limit()
            
            prompt = f"""
            Create a professional children's book cover illustration featuring a child as the main character.
            
            BOOK DETAILS:
            - Title: "{story_data['titulo']}"
            - Theme: {story_data['tema']}
            - Child's name: {book.child_name}
            - Age: {book.child_age} years old
            
            STYLE REQUIREMENTS:
            - HIGH QUALITY children's book illustration style
            - Bright, colorful, professional book cover quality
            - Show the title "{story_data['titulo']}" prominently at the top
            - Include "Un cuento para {book.child_name}" as subtitle
            - Make it look like a premium children's book cover
            - Professional book cover layout with excellent typography
            - The background should beautifully represent the story theme: {story_data['tema']}
            """
            
            image_url = await self._generate_gpt_image(prompt, book.original_photo_path, quality="hd")  # HD para portada final
            
            if image_url:
                cover_filename = f"cover_final_{book.child_name}_{book.id[:8]}.png"
                cover_path = settings.books_dir / cover_filename
                
                if await self._download_and_save_image(image_url, cover_path):
                    print(f"✅ Portada final generada: {cover_filename}")
                    return str(cover_filename)
            
            return None
            
        except Exception as e:
            print(f"❌ Error generando portada final: {e}")
            return None
    
    async def _generate_page_image(self, book: Book, page_data: Dict, page_number: int) -> Optional[str]:
        """
        Generar imagen de página específica
        """
        try:
            await self._respect_rate_limit()
            
            prompt = f"""
            Create a children's book page illustration featuring a child as the main character.
            
            PAGE DETAILS:
            - Page {page_number} of {book.total_pages}
            - Text for this page: "{page_data['texto']}"
            - Child's name: {book.child_name}
            - Age: {book.child_age} years old
            - Book theme: {json.loads(book.book_data_json).get('tema', 'adventure')}
            
            ILLUSTRATION REQUIREMENTS:
            - Children's book page illustration style
            - Show the scene described in: "{page_data['texto']}"
            - The child character should be consistent and recognizable
            - Bright, colorful, age-appropriate for {book.child_age} years old
            - Professional children's book illustration quality
            - The scene should visually represent the text content
            - Include visual storytelling elements that complement the text
            
            IMPORTANT: Focus on the scene and action, the text will be added separately.
            """
            
            image_url = await self._generate_gpt_image(prompt, book.original_photo_path, quality="standard")  # Standard para páginas
            
            if image_url:
                page_filename = f"page_{page_number:02d}_{book.id[:8]}.png"
                page_path = settings.books_dir / page_filename
                
                if await self._download_and_save_image(image_url, page_path):
                    print(f"✅ Página {page_number} generada: {page_filename}")
                    return str(page_filename)
            
            return None
            
        except Exception as e:
            print(f"❌ Error generando página {page_number}: {e}")
            return None
    
    async def _create_final_pdf(self, book: Book, story_data: Dict, cover_path: Optional[str], page_paths: List[Optional[str]]) -> Optional[str]:
        """
        Crear PDF final del libro con todas las imágenes y texto
        """
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
            from reportlab.lib.units import inch
            from reportlab.lib.colors import black
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            
            pdf_filename = f"libro_{book.child_name}_{book.id[:8]}.pdf"
            pdf_path = settings.pdfs_dir / pdf_filename
            
            # Crear documento PDF
            doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
            story = []
            
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Title'],
                fontSize=24,
                spaceAfter=30,
                textColor=black,
                alignment=1  # Center
            )
            
            text_style = ParagraphStyle(
                'CustomText',
                parent=styles['Normal'],
                fontSize=14,
                spaceAfter=20,
                textColor=black,
                alignment=1  # Center
            )
            
            # Página de título
            story.append(Paragraph(story_data['titulo'], title_style))
            story.append(Spacer(1, 0.5*inch))
            story.append(Paragraph(f"Un cuento personalizado para {book.child_name}", text_style))
            story.append(Spacer(1, 0.5*inch))
            
            # Portada
            if cover_path and (settings.books_dir / cover_path).exists():
                img = RLImage(str(settings.books_dir / cover_path))
                img.drawHeight = 6*inch
                img.drawWidth = 4*inch
                story.append(img)
            
            # Páginas del libro
            for i, page_data in enumerate(story_data['paginas'], 1):
                story.append(Spacer(1, 0.5*inch))
                
                # Imagen de la página
                page_image_path = page_paths[i-1] if i-1 < len(page_paths) and page_paths[i-1] else None
                if page_image_path and (settings.books_dir / page_image_path).exists():
                    img = RLImage(str(settings.books_dir / page_image_path))
                    img.drawHeight = 5*inch
                    img.drawWidth = 4*inch
                    story.append(img)
                    story.append(Spacer(1, 0.2*inch))
                
                # Texto de la página
                story.append(Paragraph(page_data['texto'], text_style))
                
                # Salto de página excepto en la última
                if i < len(story_data['paginas']):
                    story.append(Spacer(1, 2*inch))
            
            # Generar PDF
            doc.build(story)
            
            print(f"📄 PDF generado: {pdf_filename}")
            return pdf_filename
            
        except Exception as e:
            print(f"❌ Error creando PDF: {e}")
            return None
    
    def _fallback_story(self, child_name: str, age: int, num_pages: int) -> Dict:
        """Historia de respaldo si falla la generación"""
        pages = []
        for i in range(1, num_pages + 1):
            if i == 1:
                text = f"Érase una vez {child_name}, un niño muy especial."
            elif i == num_pages:
                text = f"Y {child_name} vivió feliz para siempre."
            else:
                text = f"{child_name} continuó su increíble aventura."
            
            pages.append({"numero": i, "texto": text})
        
        return {
            "titulo": f"Las Aventuras de {child_name}",
            "tema": "Aventura y amistad",
            "resumen": f"Una historia especial sobre las aventuras de {child_name}",
            "paginas": pages
        }
    
    async def _download_and_save_image(self, image_url: str, save_path: Path) -> bool:
        """Descargar imagen de URL y guardar localmente"""
        try:
            import aiohttp
            import aiofiles
            
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as response:
                    if response.status == 200:
                        content = await response.read()
                        
                        async with aiofiles.open(save_path, 'wb') as f:
                            await f.write(content)
                        
                        return True
            
            return False
            
        except Exception as e:
            print(f"❌ Error descargando imagen: {e}")
            return False

# Instancia global del servicio
openai_service = None

def get_openai_service() -> OpenAIService:
    """Obtener instancia del servicio OpenAI"""
    global openai_service
    if openai_service is None:
        openai_service = OpenAIService()
    return openai_service