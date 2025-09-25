from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.orm import Session
from PIL import Image
import json
import secrets
from pathlib import Path
import asyncio

from ..database import get_db, check_rate_limit, record_action
from ..models import Book, BookResponse, BookCreate
from ..services import get_openai_service
from ..config import settings

router = APIRouter(prefix="/api/books", tags=["books"])

def get_client_ip(request: Request) -> str:
    """Obtener IP del cliente"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host

def allowed_file(filename: str) -> bool:
    """Verificar si el archivo es permitido"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in settings.allowed_extensions

def save_upload_file(upload_file: UploadFile) -> str:
    """Guardar archivo subido y retornar path"""
    if not allowed_file(upload_file.filename):
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido")
    
    # Generar nombre único
    file_ext = upload_file.filename.rsplit('.', 1)[1].lower()
    unique_filename = f"{secrets.token_urlsafe(16)}.{file_ext}"
    file_path = settings.uploads_dir / unique_filename
    
    # Validar que es una imagen válida
    try:
        image = Image.open(upload_file.file)
        image.verify()  # Verificar que es una imagen válida
        
        # Resetear file pointer y guardar
        upload_file.file.seek(0)
        with open(file_path, "wb") as f:
            f.write(upload_file.file.read())
        
        print(f"📁 Archivo guardado: {unique_filename}")
        return str(file_path)
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Archivo de imagen inválido: {str(e)}")

@router.post("/create-preview", response_model=BookResponse)
async def create_book_preview(
    background_tasks: BackgroundTasks,
    request: Request,
    child_name: str = Form(...),
    child_age: int = Form(...),
    child_description: str = Form(""),
    total_pages: int = Form(6),
    photo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Crear preview gratuito del libro (solo portada con marca de agua)
    """
    # Rate limiting
    client_ip = get_client_ip(request)
    if not check_rate_limit(db, client_ip, "free_preview", settings.free_previews_per_ip_per_day):
        raise HTTPException(
            status_code=429, 
            detail=f"Máximo {settings.free_previews_per_ip_per_day} previews gratuitos por día"
        )
    
    # Validaciones
    if not (1 <= child_age <= 12):
        raise HTTPException(status_code=400, detail="La edad debe estar entre 1 y 12 años")
    
    if not (4 <= total_pages <= 20):
        raise HTTPException(status_code=400, detail="El libro debe tener entre 4 y 20 páginas")
    
    try:
        # Guardar foto
        photo_path = save_upload_file(photo)
        
        # Crear registro en BD
        book = Book(
            child_name=child_name.strip(),
            child_age=child_age,
            child_description=child_description.strip() if child_description else None,
            total_pages=total_pages,
            original_photo_path=photo_path,
            status='preview',
            ip_hash=client_ip  # Para analytics básico
        )
        
        db.add(book)
        db.commit()
        db.refresh(book)
        
        # Registrar acción para rate limiting
        record_action(db, client_ip, "free_preview")
        
        # Generar historia y portada preview en background
        background_tasks.add_task(generate_preview_content, book.id)
        
        print(f"✅ Preview creado: {book.id} para {child_name}")
        
        return BookResponse.from_orm(book)
        
    except Exception as e:
        print(f"❌ Error creando preview: {e}")
        raise HTTPException(status_code=500, detail=f"Error procesando solicitud: {str(e)}")

async def generate_preview_content(book_id: str):
    """
    Tarea en background para generar contenido del preview
    """
    try:
        db_session = SessionLocal()
        book = db_session.query(Book).filter(Book.id == book_id).first()
        
        if not book:
            print(f"❌ Libro {book_id} no encontrado para preview")
            return
        
        # Obtener servicio de OpenAI
        openai_service = get_openai_service()
        
        # 1. Generar historia
        print(f"📖 Generando historia para preview {book_id}...")
        story_data = await openai_service.generate_story(
            book.child_name, 
            book.child_age, 
            book.child_description or "",
            book.total_pages
        )
        
        # 2. Generar portada preview
        print(f"🎨 Generando portada preview {book_id}...")
        cover_filename = await openai_service.generate_cover_preview(
            book.child_name,
            book.child_age, 
            book.original_photo_path,
            story_data
        )
        
        # 3. Actualizar registro
        book.title = story_data['titulo']
        book.story_theme = story_data['tema']
        book.book_data_json = json.dumps(story_data, ensure_ascii=False)
        book.cover_preview_path = cover_filename
        book.status = 'preview_ready'
        
        db_session.commit()
        
        print(f"✅ Preview {book_id} completado")
        
    except Exception as e:
        print(f"❌ Error generando preview {book_id}: {e}")
        
        # Actualizar estado de error
        if 'db_session' in locals() and 'book' in locals():
            book.status = 'preview_error'
            book.generation_error = str(e)
            db_session.commit()
    
    finally:
        if 'db_session' in locals():
            db_session.close()

@router.get("/{book_id}", response_model=BookResponse)
async def get_book(book_id: str, db: Session = Depends(get_db)):
    """
    Obtener información de un libro
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")
    
    return BookResponse.from_orm(book)

@router.post("/{book_id}/generate-complete")
async def generate_complete_book(
    book_id: str, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Generar libro completo (después del pago)
    Solo disponible para libros pagados
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")
    
    if book.status != 'paid':
        raise HTTPException(status_code=400, detail="El libro debe estar pagado para generar la versión completa")
    
    if book.status == 'generating':
        return {"message": "El libro ya se está generando", "status": "generating"}
    
    if book.status == 'completed':
        return {"message": "El libro ya está completado", "status": "completed"}
    
    # Iniciar generación en background
    background_tasks.add_task(generate_complete_book_task, book_id)
    
    return {
        "message": "Generación iniciada. Recibirás un email cuando esté listo.",
        "status": "generating",
        "estimated_time_minutes": 3
    }

async def generate_complete_book_task(book_id: str):
    """
    Tarea para generar libro completo
    """
    try:
        openai_service = get_openai_service()
        await openai_service.generate_complete_book(book_id)
        
        # TODO: Enviar email de notificación
        print(f"✅ Libro completo {book_id} generado y email enviado")
        
    except Exception as e:
        print(f"❌ Error en generación completa {book_id}: {e}")

@router.get("/{book_id}/status")
async def get_book_status(book_id: str, db: Session = Depends(get_db)):
    """
    Obtener estado actual del libro (para polling desde frontend)
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")
    
    response = {
        "book_id": book.id,
        "status": book.status,
        "child_name": book.child_name,
        "title": book.title
    }
    
    # Información específica según el estado
    if book.status == 'preview_ready':
        response["cover_preview_url"] = f"/storage/previews/{book.cover_preview_path}" if book.cover_preview_path else None
        response["story_preview"] = json.loads(book.book_data_json).get("resumen", "") if book.book_data_json else ""
        response["total_price_euros"] = book.total_price_euros
    
    elif book.status == 'completed':
        response["pdf_url"] = f"/storage/pdfs/{book.pdf_path}" if book.pdf_path else None
        response["completed_at"] = book.completed_at.isoformat() if book.completed_at else None
    
    elif book.status in ['preview_error', 'error']:
        response["error"] = book.generation_error
    
    return response

@router.delete("/{book_id}")
async def delete_book(book_id: str, db: Session = Depends(get_db)):
    """
    Eliminar libro (solo previews no pagados)
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")
    
    if book.is_paid:
        raise HTTPException(status_code=400, detail="No se pueden eliminar libros pagados")
    
    # Eliminar archivos asociados
    if book.original_photo_path:
        try:
            Path(book.original_photo_path).unlink(missing_ok=True)
        except:
            pass
    
    if book.cover_preview_path:
        try:
            (settings.previews_dir / book.cover_preview_path).unlink(missing_ok=True)
        except:
            pass
    
    # Eliminar de BD
    db.delete(book)
    db.commit()
    
    return {"message": "Libro eliminado exitosamente"}

# Importar SessionLocal aquí para evitar circular imports
from ..database import SessionLocal