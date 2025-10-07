from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from PIL import Image
import json
import secrets
from pathlib import Path

from sqlalchemy.sql import func

from ..database import get_db, check_rate_limit, record_action, SessionLocal
from ..models import Book, BookResponse
from ..services import get_book_service
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
    """Guardar archivo subido"""
    if not allowed_file(upload_file.filename):
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido")
    
    file_ext = upload_file.filename.rsplit('.', 1)[1].lower()
    unique_filename = f"{secrets.token_urlsafe(16)}.{file_ext}"
    file_path = settings.uploads_dir / unique_filename
    
    try:
        image = Image.open(upload_file.file)
        image.verify()
        
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
    Crear preview usando solo Gemini (historia + portada)
    """
    # Rate limiting
    client_ip = get_client_ip(request)
    if not check_rate_limit(db, client_ip, "free_preview", settings.free_previews_per_ip_per_day):
        raise HTTPException(
            status_code=429, 
            detail=f"Máximo {settings.free_previews_per_ip_per_day} previews por día"
        )
    
    # Validaciones
    if not (1 <= child_age <= 12):
        raise HTTPException(status_code=400, detail="Edad entre 1 y 12 años")
    
    if not (4 <= total_pages <= 20):
        raise HTTPException(status_code=400, detail="Entre 4 y 20 páginas")
    
    try:
        # Guardar foto
        photo_path = save_upload_file(photo)
        
        # Crear libro en BD
        book = Book(
            child_name=child_name.strip(),
            child_age=child_age,
            child_description=child_description.strip() if child_description else None,
            total_pages=total_pages,
            original_photo_path=photo_path,
            status='preview',
            ip_hash=client_ip
        )
        
        db.add(book)
        db.commit()
        db.refresh(book)
        
        # Registrar acción
        record_action(db, client_ip, "free_preview")
        
        # Generar en background
        background_tasks.add_task(generate_preview_with_gemini, book.id)
        
        print(f"✅ Preview creado: {book.id}")
        return BookResponse.from_orm(book)
        
    except Exception as e:
        print(f"❌ Error creando preview: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def generate_preview_with_gemini(book_id: str):
    """
    Generar preview: Gemini para historia y portada
    """
    try:
        db_session = SessionLocal()
        book = db_session.query(Book).filter(Book.id == book_id).first()
        
        if not book:
            print(f"❌ Libro {book_id} no encontrado")
            return
        
        service = get_book_service()
        
        # 1. Gemini: Analizar foto + generar historia
        print(f"🤖 Gemini generando historia para {book_id}...")
        story_data = await service.gemini.generate_story_from_photo(
            photo_path=book.original_photo_path,
            child_name=book.child_name,
            age=book.child_age,
            description=book.child_description or "",
            num_pages=book.total_pages
        )
        
        # 2. Gemini Image: Generar portada preview
        print(f"🎨 Gemini generando portada para {book_id}...")
        cover_filename = await service.gemini_image.generate_cover(
            story_data=story_data,
            reference_image_path=book.original_photo_path
        )
        
        # 3. Actualizar BD
        book.title = story_data['titulo']
        book.story_theme = story_data.get('tema', '')
        book.book_data_json = json.dumps(story_data, ensure_ascii=False)
        book.cover_preview_path = cover_filename
        book.status = 'preview_ready'
        
        db_session.commit()
        print(f"✅ Preview {book_id} completado")
        
    except Exception as e:
        print(f"❌ Error generando preview {book_id}: {e}")
        
        if 'db_session' in locals() and 'book' in locals():
            book.status = 'preview_error'
            book.generation_error = str(e)
            db_session.commit()
    
    finally:
        if 'db_session' in locals():
            db_session.close()

@router.get("/{book_id}", response_model=BookResponse)
async def get_book(book_id: str, db: Session = Depends(get_db)):
    """Obtener información de un libro"""
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
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")
    
    if book.status != 'paid':
        raise HTTPException(status_code=400, detail="Debe estar pagado")
    
    if book.status == 'generating':
        return {"message": "Ya se está generando", "status": "generating"}
    
    if book.status == 'completed':
        return {"message": "Ya está completado", "status": "completed"}
    
    # Generar en background
    service = get_book_service()
    background_tasks.add_task(service.generate_complete_book, book_id)
    
    return {
        "message": "Generación iniciada",
        "status": "generating",
        "estimated_time_minutes": 5
    }

@router.get("/{book_id}/status")
async def get_book_status(book_id: str, db: Session = Depends(get_db)):
    """Estado del libro (para polling)"""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")
    
    response = {
        "book_id": book.id,
        "status": book.status,
        "child_name": book.child_name,
        "title": book.title
    }
    
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
    """Eliminar libro (solo previews no pagados)"""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")
    
    if book.is_paid:
        raise HTTPException(status_code=400, detail="No se pueden eliminar libros pagados")
    
    # Eliminar archivos
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

@router.post("/{book_id}/simulate-payment")
async def simulate_payment(
    book_id: str,
    password: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Simular pago con contraseña (solo para debug)
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")
    
    if book.status != 'preview_ready':
        raise HTTPException(status_code=400, detail="El libro debe estar en preview_ready")
    
    # Verificar contraseña
    if password.get('password') != settings.debug_payment_password:
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    
    # Marcar como pagado
    book.status = 'paid'
    book.amount_paid = book.total_price_cents
    book.paid_at = func.now()
    book.payment_intent_id = f"debug_{secrets.token_urlsafe(16)}"
    db.commit()
    
    print(f"💰 Pago simulado exitoso para libro {book_id}")
    
    # Generar libro completo en background
    service = get_book_service()
    background_tasks.add_task(service.generate_complete_book, book_id)
    
    return {
        "message": "Pago simulado exitoso",
        "book_id": book.id,
        "status": "paid",
        "generating": True
    }