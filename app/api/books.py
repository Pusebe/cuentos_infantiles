from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from PIL import Image
import json
import secrets
from pathlib import Path

from sqlalchemy.sql import func

from ..database import get_db, check_rate_limit, record_action, SessionLocal
from ..models import Book, BookResponse, RegenerationRequest
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
    photo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Crear preview: historia + sheets + portada (12 páginas fijas)
    """
    # Rate limiting
    client_ip = get_client_ip(request)
    if not check_rate_limit(db, client_ip, "free_preview", settings.free_previews_per_ip_per_day):
        raise HTTPException(
            status_code=429, 
            detail=f"Máximo {settings.free_previews_per_ip_per_day} previews por día"
        )
    
    # Validaciones
    if not (1 <= child_age <= 99):
        raise HTTPException(status_code=400, detail="Edad entre 1 y 99 años")
    
    try:
        # Guardar foto
        photo_path = save_upload_file(photo)
        
        # Crear libro en BD con 12 páginas fijas
        book = Book(
            child_name=child_name.strip(),
            child_age=child_age,
            child_description=child_description.strip() if child_description else None,
            total_pages=12,  # FIJO
            original_photo_path=photo_path,
            status='preview',
            current_step='Iniciando',
            progress_percentage=0,
            ip_hash=client_ip
        )
        
        db.add(book)
        db.commit()
        db.refresh(book)
        
        # Registrar acción
        record_action(db, client_ip, "free_preview")
        
        # Generar en background con nuevo sistema de sheets
        service = get_book_service()
        background_tasks.add_task(service.generate_preview_with_sheets, book.id)
        
        print(f"✅ Preview creado: {book.id}")
        return BookResponse.from_orm(book)
        
    except Exception as e:
        print(f"❌ Error creando preview: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{book_id}/regenerate-preview")
async def regenerate_preview(
    book_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Regenerar SOLO la portada del preview (mantiene historia y sheets)
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")
    
    if book.status != 'preview_ready':
        raise HTTPException(status_code=400, detail="Solo se puede regenerar en preview_ready")
    
    # Rate limiting: 3 regeneraciones por día
    client_ip = get_client_ip(request)
    if not check_rate_limit(db, client_ip, "regenerate_preview", 3):
        raise HTTPException(
            status_code=429, 
            detail="Máximo 3 regeneraciones por día"
        )
    
    # Registrar acción
    record_action(db, client_ip, "regenerate_preview")
    
    # Regenerar en background
    service = get_book_service()
    background_tasks.add_task(service.regenerate_preview_cover, book_id)
    
    return {"message": "Regeneración iniciada", "book_id": book_id}

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
    Generar libro completo (después del pago) usando sheets
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
    """Estado del libro (para polling) con información detallada"""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")
    
    response = {
        "book_id": book.id,
        "status": book.status,
        "child_name": book.child_name,
        "title": book.title,
        "current_step": book.current_step,
        "progress_percentage": book.progress_percentage or 0
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

@router.post("/{book_id}/request-regeneration")
async def request_page_regeneration(
    book_id: str,
    request: Request,
    data: dict,
    db: Session = Depends(get_db)
):
    """
    Solicitar regeneración de una página específica (cliente)
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")
    
    if book.status != 'completed':
        raise HTTPException(status_code=400, detail="El libro debe estar completado")
    
    page_number = data.get('page_number')
    reason = data.get('reason', '')
    
    if not page_number or page_number < 1 or page_number > book.total_pages:
        raise HTTPException(status_code=400, detail="Número de página inválido")
    
    # Crear petición
    regen_request = RegenerationRequest(
        book_id=book_id,
        page_number=page_number,
        reason=reason,
        status='pending'
    )
    
    db.add(regen_request)
    db.commit()
    
    print(f"📤 Petición de regeneración creada: Página {page_number} del libro {book_id}")
    
    return {
        "message": "Solicitud enviada correctamente",
        "request_id": regen_request.id,
        "status": "pending"
    }

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
    
    # Eliminar sheets si existen
    try:
        char_sheet = settings.assets_dir / f"{book.child_name}_{book.id[:8]}_characters.png"
        scene_sheet = settings.assets_dir / f"{book.child_name}_{book.id[:8]}_scenes.png"
        char_sheet.unlink(missing_ok=True)
        scene_sheet.unlink(missing_ok=True)
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