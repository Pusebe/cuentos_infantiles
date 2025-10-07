import google.generativeai as genai
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
        - Cada página: unas pocas (en funcion de la edad) frases cortas (ideales para ilustrar) 
        - Historia emocionante que los padres quieran comprar
        - Final feliz con lección positiva
        - IMPORTANTE: Lista todos los personajes y objetos clave que aparecen en cada página para mantener consistencia visual

        RESPONDE EN FORMATO JSON EXACTO:
        {{
            "child_description": "Descripción física detallada del niño de la foto",
            "scene_context": "Descripción del fondo y ambiente de la foto",
            "titulo": "Título atractivo del libro",
            "tema": "Tema principal (aventura, amistad, etc)",
            "resumen": "Resumen de 1 frase",
            "leccion": "Qué aprenderá el niño",
            "paginas": [
                {{
                    "numero": 1, 
                    "texto": "Texto de la página 1", 
                    "escena": "Descripción de qué ilustrar",
                    "personajes_presentes": ["nombre (descripción física breve)"],
                    "objetos_clave": ["objeto importante con detalles"]
                }},
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
            
            # Añadir child_name al story_data
            data['child_name'] = child_name
            
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
                            "personajes_presentes": [f"{child_name}"],
                            "objetos_clave": []
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
                "personajes_presentes": [f"{child_name}"],
                "objetos_clave": []
            })
        
        return {
            "child_name": child_name,
            "child_description": f"Niño de {age} años llamado {child_name}",
            "scene_context": "Ambiente de aventura",
            "titulo": f"Las Aventuras de {child_name}",
            "tema": "Aventura",
            "resumen": f"Una historia sobre {child_name}",
            "leccion": "Valentía y amistad",
            "paginas": pages
        }


class GeminiImageService:
    """Servicio para Gemini 2.5 Flash Image - Generación de imágenes (portadas y páginas)"""
    
    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY no configurada")
        
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash-image-preview')
        self.last_request = 0
        self.min_delay = 1  # Rate limiting
        print("🎨 Gemini Image Service configurado")
    
    async def generate_cover(self, story_data: Dict, reference_image_path: str) -> Optional[str]:
        """Genera portada con Gemini"""
        try:
            child_name = story_data.get('child_name', 'el niño')
            child_desc = story_data.get('child_description', 'un niño')
            tema = story_data.get('tema', 'aventura')
            titulo = story_data['titulo']
            
            prompt = f"Portada profesional de libro infantil en formato cuadrado 1:1 con el título {titulo} y subtítulo Un cuento para {child_name} con ilustración colorida estilo animación mostrando como personaje principal a {child_desc} en una escena de {tema}. Deja el 25% inferior de la imagen con colores suaves sin elementos importantes para añadir texto después."
            
            print(f"📝 Generando portada con Gemini...")
            
            # Usar foto como referencia
            reference_image = Image.open(reference_image_path)
            
            await self._respect_rate_limit()
            
            response = await asyncio.to_thread(
                self.model.generate_content,
                [prompt, reference_image]
            )
            
            # Extraer y guardar imagen
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        image_data = part.inline_data.data
                        filename = f"cover_{secrets.token_urlsafe(8)}.png"
                        file_path = settings.previews_dir / filename
                        
                        async with aiofiles.open(file_path, 'wb') as f:
                            await f.write(image_data)
                        
                        print(f"✅ Portada generada: {filename}")
                        return str(filename)
            
            print("❌ No se pudo extraer portada de Gemini")
            return None
            
        except Exception as e:
            print(f"❌ Error generando portada con Gemini: {e}")
            return None
    
    async def generate_page_image(self, prompt: str, reference_images: List[str]) -> Optional[str]:
        """
        Genera imagen con Gemini usando múltiples imágenes de referencia (collage)
        """
        try:
            await self._respect_rate_limit()
            
            # Crear collage de referencias si hay múltiples
            if len(reference_images) > 1:
                collage_path = await self._create_reference_collage(reference_images)
                reference_image = Image.open(collage_path)
            else:
                reference_image = Image.open(reference_images[0])
            
            # Generar imagen
            response = await asyncio.to_thread(
                self.model.generate_content,
                [prompt, reference_image]
            )
            
            # Extraer y guardar imagen
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                        image_data = part.inline_data.data
                        filename = f"gemini_page_{secrets.token_urlsafe(8)}.png"
                        file_path = settings.books_dir / filename
                        
                        async with aiofiles.open(file_path, 'wb') as f:
                            await f.write(image_data)
                        
                        return str(filename)
            
            print("❌ No se pudo extraer imagen de la respuesta de Gemini")
            return None
            
        except Exception as e:
            print(f"❌ Error generando imagen con Gemini: {e}")
            return None
    
    async def _create_reference_collage(self, image_paths: List[str]) -> str:
        """Crear collage de imágenes de referencia"""
        try:
            from PIL import Image as PILImage
            
            # Limitar a máximo 4 referencias (2x2 grid)
            paths = image_paths[:4]
            images = [PILImage.open(p) for p in paths]
            
            # Redimensionar todas a mismo tamaño
            size = 512
            images = [img.resize((size, size), PILImage.Resampling.LANCZOS) for img in images]
            
            # Crear collage
            if len(images) == 1:
                collage = images[0]
            elif len(images) == 2:
                collage = PILImage.new('RGB', (size * 2, size))
                collage.paste(images[0], (0, 0))
                collage.paste(images[1], (size, 0))
            elif len(images) == 3:
                collage = PILImage.new('RGB', (size * 2, size * 2))
                collage.paste(images[0], (0, 0))
                collage.paste(images[1], (size, 0))
                collage.paste(images[2], (0, size))
            else:  # 4 imágenes
                collage = PILImage.new('RGB', (size * 2, size * 2))
                collage.paste(images[0], (0, 0))
                collage.paste(images[1], (size, 0))
                collage.paste(images[2], (0, size))
                collage.paste(images[3], (size, size))
            
            # Guardar collage temporal
            collage_path = settings.books_dir / f"collage_{secrets.token_urlsafe(8)}.png"
            collage.save(collage_path)
            
            return str(collage_path)
            
        except Exception as e:
            print(f"❌ Error creando collage: {e}")
            # Fallback: devolver primera imagen
            return image_paths[0]
    
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
        self.gemini_image = GeminiImageService()
    
    async def generate_complete_book(self, book_id: str):
        """
        Generar libro completo: reutilizar portada + páginas con Gemini + PDF
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
            
            # 1. Verificar que existe la portada del preview
            if not book.cover_preview_path:
                print("❌ No hay portada de preview, generando con Gemini...")
                cover_filename = await self.gemini_image.generate_cover(
                    story_data,
                    book.original_photo_path
                )
                if not cover_filename:
                    raise Exception("No se pudo generar la portada")
            else:
                print(f"✅ Reutilizando portada existente: {book.cover_preview_path}")
                cover_filename = book.cover_preview_path
            
            # 2. Generar páginas con Gemini usando collage de referencias
            page_filenames = []
            reference_images = [str(settings.previews_dir / cover_filename)]  # Empezar con portada
            
            for i, page_data in enumerate(story_data['paginas'], 1):
                print(f"🖼️ Generando página {i}/{len(story_data['paginas'])} con Gemini...")
                
                # Construir prompt con personajes y objetos
                personajes = page_data.get('personajes_presentes', [])
                objetos = page_data.get('objetos_clave', [])
                
                personajes_str = f"Personajes: {', '.join(personajes)}. " if personajes else ""
                objetos_str = f"Objetos importantes: {', '.join(objetos)}. " if objetos else ""
                
                prompt = f"Genera una ilustración de cuento infantil mostrando: {page_data.get('escena', page_data['texto'])}. {personajes_str}{objetos_str}Estilo de ilustración colorida apropiada para niños con el tercio inferior con tonos suaves ideal para añadir texto. SIN NINGÚN TEXTO en la imagen. Mantén consistencia con las imágenes de referencia."
                
                page_filename = await self.gemini_image.generate_page_image(
                    prompt,
                    reference_images[-3:]  # Últimas 3 referencias (portada + 2 páginas anteriores)
                )
                
                if not page_filename:
                    print(f"⚠️ Falló página {i}, continuando...")
                    page_filenames.append(None)
                    continue
                
                page_filenames.append(page_filename)
                
                # Añadir página generada al pool de referencias
                reference_images.append(str(settings.books_dir / page_filename))
            
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
        """Crear PDF final con imágenes a página completa y texto superpuesto"""
        try:
            from reportlab.lib.pagesizes import inch
            from reportlab.pdfgen import canvas
            from reportlab.lib.colors import Color
            
            PAGE_SIZE = (8.5*inch, 8.5*inch)  # Cuadrado 8.5x8.5"
            
            pdf_filename = f"libro_{book.child_name}_{book.id[:8]}.pdf"
            pdf_path = settings.pdfs_dir / pdf_filename
            
            # Crear canvas para control total
            c = canvas.Canvas(str(pdf_path), pagesize=PAGE_SIZE)
            width, height = PAGE_SIZE
            
            # Portada a página completa
            if cover_filename:
                cover_path = settings.previews_dir / cover_filename
                if cover_path.exists():
                    c.drawImage(str(cover_path), 0, 0, width=width, height=height, preserveAspectRatio=True, anchor='c')
                    c.showPage()
            
            # Páginas con imagen completa + texto superpuesto
            for i, page_data in enumerate(story_data['paginas'], 1):
                page_filename = page_filenames[i-1] if i-1 < len(page_filenames) else None
                
                if page_filename:
                    page_path = settings.books_dir / page_filename
                    if page_path.exists():
                        # Imagen a página completa
                        c.drawImage(str(page_path), 0, 0, width=width, height=height, preserveAspectRatio=True, anchor='c')
                
                # Área de texto con fondo semi-transparente
                text_height = 2*inch
                c.setFillColor(Color(0, 0, 0, alpha=0.5))  # Negro 50% transparente
                c.rect(0, 0, width, text_height, fill=1, stroke=0)
                
                # Texto en blanco
                c.setFillColor(Color(1, 1, 1, alpha=1))  # Blanco
                c.setFont("Helvetica-Bold", 18)
                
                texto = page_data['texto']
                # Word wrap simple
                max_width = width - inch
                lines = []
                words = texto.split()
                current_line = ""
                
                for word in words:
                    test_line = current_line + " " + word if current_line else word
                    if c.stringWidth(test_line, "Helvetica-Bold", 18) < max_width:
                        current_line = test_line
                    else:
                        if current_line:
                            lines.append(current_line)
                        current_line = word
                
                if current_line:
                    lines.append(current_line)
                
                # Dibujar líneas alineadas a la izquierda
                y_start = text_height - 0.5*inch
                x_left = 0.5*inch  # Margen izquierdo
                for line in lines:
                    c.drawString(x_left, y_start, line)
                    y_start -= 24  # Espaciado entre líneas
                
                c.showPage()
            
            c.save()
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