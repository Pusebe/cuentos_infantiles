"""
Orquestador principal para generación de libros
"""

import json
from typing import Optional
from sqlalchemy.sql import func
from pathlib import Path

from .gemini_text import GeminiTextService
from .gemini_image import GeminiImageService
from .ideogram_image import IdeogramImageService
from .pdf_generator import PDFGenerator
from ..database import SessionLocal
from ..models import Book
from ..config import settings


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


class BookOrchestrator:
    """Orquestador para generación de libros completos"""
    
    def __init__(self):
        self.gemini_text = GeminiTextService()
        self.gemini_image = GeminiImageService()
        self.ideogram_image = IdeogramImageService()
        self.pdf_generator = PDFGenerator()
        print("🎯 Book Orchestrator inicializado")
    
    async def generate_preview(self, book_id: str):
        """
        Generar PREVIEW RÁPIDO: historia mínima + portada ilustrada
        Total: ~30-40 segundos
        """
        try:
            db = SessionLocal()
            book = db.query(Book).filter(Book.id == book_id).first()
            if not book:
                print(f"❌ Libro {book_id} no encontrado")
                return
            
            # 1. Generar historia MÍNIMA (rápido)
            update_book_progress(book_id, "Creando la idea del cuento", 20)
            print(f"🤖 Generando historia mínima...")
            minimal_story = await self.gemini_text.generate_minimal_story(
                photo_path=book.original_photo_path,
                child_name=book.child_name,
                age=book.child_age,
                description=book.child_description or ""
            )
            
            # Guardar edad en la historia
            minimal_story['age'] = book.child_age
            
            # 2. Generar portada con IDEOGRAM (acepta descripciones de personas)
            update_book_progress(book_id, "Transformando en portada mágica", 60)
            print(f"🎨 Generando portada con Ideogram...")
            cover_filename = None
            for attempt in range(1, 4):
                print(f"  Intento {attempt}/3...")
                cover_filename = await self.ideogram_image.generate_cover(
                    story_data=minimal_story,
                    reference_photo_path=book.original_photo_path
                )
                if cover_filename:
                    break
                if attempt < 3:
                    print(f"  ⚠️ Reintentando en 2 segundos...")
                    import asyncio
                    await asyncio.sleep(2)
            
            if not cover_filename:
                raise Exception("No se pudo generar portada después de 3 intentos")
            
            # 3. Actualizar BD (guardar historia MÍNIMA)
            update_book_progress(book_id, "Preview listo", 100)
            book.title = minimal_story['titulo']
            book.story_theme = minimal_story.get('tema', '')
            book.book_data_json = json.dumps(minimal_story, ensure_ascii=False)
            book.cover_preview_path = cover_filename
            book.status = 'preview_ready'
            
            db.commit()
            print(f"✅ Preview {book_id} completado (rápido)")
            
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
        """Regenerar SOLO la portada del preview"""
        try:
            db = SessionLocal()
            book = db.query(Book).filter(Book.id == book_id).first()
            if not book:
                print(f"❌ Libro {book_id} no encontrado")
                return False
            
            if not book.book_data_json:
                raise Exception("No hay historia para regenerar")
            
            minimal_story = json.loads(book.book_data_json)
            minimal_story['age'] = book.child_age
            
            # Actualizar estado
            book.status = 'generating_cover'
            book.current_step = "Regenerando portada"
            book.progress_percentage = 50
            db.commit()
            
            # Regenerar portada CON RETRY (usando Ideogram)
            print(f"🔄 Regenerando portada con Ideogram...")
            cover_filename = None
            for attempt in range(1, 4):
                print(f"  Intento {attempt}/3...")
                cover_filename = await self.ideogram_image.generate_cover(
                    story_data=minimal_story,
                    reference_photo_path=book.original_photo_path
                )
                if cover_filename:
                    break
                if attempt < 3:
                    print(f"  ⚠️ Reintentando en 2 segundos...")
                    import asyncio
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
        """
        Generar libro completo DESPUÉS DEL PAGO:
        1. Extender historia mínima a completa
        2. Generar sheets
        3. Generar 12 páginas
        4. Crear PDF
        """
        try:
            db = SessionLocal()
            book = db.query(Book).filter(Book.id == book_id).first()
            if not book:
                print(f"❌ Libro {book_id} no encontrado")
                return
            
            book.status = 'generating'
            book.current_step = "Iniciando generación completa"
            book.progress_percentage = 0
            db.commit()
            
            minimal_story = json.loads(book.book_data_json)
            cover_path = settings.previews_dir / book.cover_preview_path
            
            print(f"🎨 Generando libro completo para {book.child_name}...")
            
            # 1. EXTENDER historia mínima a completa (con 12 páginas + personajes + objetos + escenarios)
            update_book_progress(book_id, "Extendiendo historia completa", 5)
            print(f"📖 Extendiendo historia a 12 páginas...")
            full_story = await self.gemini_text.extend_full_story(
                minimal_story=minimal_story,
                num_pages=book.total_pages
            )
            
            # Guardar historia completa
            book.book_data_json = json.dumps(full_story, ensure_ascii=False)
            db.commit()
            
            # 2. Generar character sheet (basado en portada)
            update_book_progress(book_id, "Creando personajes con portada", 10)
            print(f"🎨 Generando character sheet...")
            char_sheet_filename = None
            for attempt in range(1, 4):
                print(f"  Intento {attempt}/3...")
                char_sheet_filename = await self.gemini_image.generate_character_sheet(
                    story_data=full_story,
                    cover_image_path=str(cover_path)
                )
                if char_sheet_filename:
                    break
                if attempt < 3:
                    print(f"  ⚠️ Reintentando en 2 segundos...")
                    import asyncio
                    await asyncio.sleep(2)
            
            if not char_sheet_filename:
                raise Exception("No se pudo generar character sheet después de 3 intentos")
            
            char_sheet_path = settings.assets_dir / char_sheet_filename
            
            # 3. Generar scene sheet
            update_book_progress(book_id, "Creando escenarios", 20)
            print(f"🏞️ Generando scene sheet...")
            scene_sheet_filename = None
            for attempt in range(1, 4):
                print(f"  Intento {attempt}/3...")
                scene_sheet_filename = await self.gemini_image.generate_scene_sheet(
                    story_data=full_story
                )
                if scene_sheet_filename:
                    break
                if attempt < 3:
                    print(f"  ⚠️ Reintentando en 2 segundos...")
                    import asyncio
                    await asyncio.sleep(2)
            
            if not scene_sheet_filename:
                raise Exception("No se pudo generar scene sheet después de 3 intentos")
            
            scene_sheet_path = settings.assets_dir / scene_sheet_filename
            
            # 4. Generar páginas con RETRY
            page_filenames = []
            failed_pages = []
            total_pages = len(full_story['paginas'])
            
            for i, page_data in enumerate(full_story['paginas'], 1):
                progress = int(20 + (i / total_pages) * 70)  # 20% a 90%
                update_book_progress(book_id, f"Generando página {i}/{total_pages}", progress)
                print(f"🖼️ Generando página {i}/{total_pages}...")
                
                page_filename = await self.gemini_image.generate_page_image_with_retry(
                    page_data=page_data,
                    character_sheet_path=str(char_sheet_path),
                    scene_sheet_path=str(scene_sheet_path),
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
            
            # 5. Crear PDF
            update_book_progress(book_id, "Creando PDF final", 95)
            print("📄 Creando PDF...")
            pdf_filename = await self.pdf_generator.create_pdf(
                book=book,
                story_data=full_story,
                cover_filename=book.cover_preview_path,
                page_filenames=page_filenames
            )
            
            if not pdf_filename:
                raise Exception("No se pudo crear el PDF")
            
            # 6. Finalizar
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
            db.close()
        finally:
            if 'db' in locals():
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
            
            # Localizar sheets en assets
            char_sheet_files = list(settings.assets_dir.glob("char_sheet_*.png"))
            scene_sheet_files = list(settings.assets_dir.glob("scene_sheet_*.png"))
            
            if not char_sheet_files or not scene_sheet_files:
                raise Exception("Sheets no encontrados")
            
            char_sheet_path = char_sheet_files[0]
            scene_sheet_path = scene_sheet_files[0]
            
            print(f"🔄 Regenerando página {page_number}...")
            
            # Regenerar página
            new_page_filename = await self.gemini_image.generate_page_image_with_retry(
                page_data=page_data,
                character_sheet_path=str(char_sheet_path),
                scene_sheet_path=str(scene_sheet_path),
                max_retries=3
            )
            
            if not new_page_filename:
                raise Exception("No se pudo regenerar la página")
            
            # Obtener lista de todas las páginas actuales
            page_filenames = []
            page_files = sorted(settings.books_dir.glob("page_*.png"))
            
            for i in range(1, len(story_data['paginas']) + 1):
                if i == page_number:
                    page_filenames.append(new_page_filename)
                elif i-1 < len(page_files):
                    page_filenames.append(page_files[i-1].name)
                else:
                    page_filenames.append(None)
            
            # Recrear PDF con la nueva página
            print("📄 Recreando PDF...")
            pdf_filename = await self.pdf_generator.create_pdf(
                book=book,
                story_data=story_data,
                cover_filename=book.cover_preview_path,
                page_filenames=page_filenames
            )
            
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
            if 'db' in locals():
                db.close()


# Singleton
_orchestrator = None

def get_book_orchestrator() -> BookOrchestrator:
    """Obtener instancia del orquestador"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = BookOrchestrator()
    return _orchestrator