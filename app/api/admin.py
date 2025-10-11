from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from typing import List
from pydantic import BaseModel

from ..database import get_db
from ..models import RegenerationRequest, Book
from ..services import get_book_orchestrator
from ..config import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Pydantic models
class RegenerationRequestResponse(BaseModel):
    id: int
    book_id: str
    page_number: int
    reason: str
    status: str
    created_at: str
    child_name: str
    book_title: str
    
    class Config:
        from_attributes = True

class ApproveRequest(BaseModel):
    password: str

@router.get("/regeneration-requests", response_model=List[RegenerationRequestResponse])
async def list_regeneration_requests(
    password: str,
    db: Session = Depends(get_db)
):
    """
    Listar todas las peticiones de regeneración pendientes
    Requiere contraseña de admin
    """
    # Verificar contraseña de admin
    if password != settings.debug_payment_password:  # Reutilizamos la misma para simplicidad
        raise HTTPException(status_code=401, detail="Contraseña de admin incorrecta")
    
    # Obtener peticiones pendientes con info del libro
    requests = db.query(RegenerationRequest).filter(
        RegenerationRequest.status == 'pending'
    ).order_by(RegenerationRequest.created_at.desc()).all()
    
    result = []
    for req in requests:
        book = db.query(Book).filter(Book.id == req.book_id).first()
        if book:
            result.append({
                "id": req.id,
                "book_id": req.book_id,
                "page_number": req.page_number,
                "reason": req.reason or "Sin razón especificada",
                "status": req.status,
                "created_at": req.created_at.isoformat(),
                "child_name": book.child_name,
                "book_title": book.title or f"Libro de {book.child_name}"
            })
    
    return result

@router.post("/regeneration/{request_id}/approve")
async def approve_regeneration(
    request_id: int,
    data: ApproveRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Aprobar y ejecutar regeneración de página
    """
    # Verificar contraseña
    if data.password != settings.debug_payment_password:
        raise HTTPException(status_code=401, detail="Contraseña de admin incorrecta")
    
    # Obtener petición
    regen_request = db.query(RegenerationRequest).filter(
        RegenerationRequest.id == request_id
    ).first()
    
    if not regen_request:
        raise HTTPException(status_code=404, detail="Petición no encontrada")
    
    if regen_request.status != 'pending':
        raise HTTPException(status_code=400, detail="Petición ya procesada")
    
    # Marcar como aprobada
    regen_request.status = 'approved'
    regen_request.processed_at = func.now()
    db.commit()
    
    # Ejecutar regeneración en background
    orchestrator = get_book_orchestrator()
    background_tasks.add_task(
        orchestrator.regenerate_single_page,
        regen_request.book_id,
        regen_request.page_number
    )
    
    print(f"✅ Regeneración aprobada: Página {regen_request.page_number} del libro {regen_request.book_id}")
    
    return {
        "message": "Regeneración aprobada y en proceso",
        "request_id": request_id,
        "book_id": regen_request.book_id,
        "page_number": regen_request.page_number
    }

@router.post("/regeneration/{request_id}/reject")
async def reject_regeneration(
    request_id: int,
    data: ApproveRequest,
    db: Session = Depends(get_db)
):
    """
    Rechazar petición de regeneración
    """
    # Verificar contraseña
    if data.password != settings.debug_payment_password:
        raise HTTPException(status_code=401, detail="Contraseña de admin incorrecta")
    
    # Obtener petición
    regen_request = db.query(RegenerationRequest).filter(
        RegenerationRequest.id == request_id
    ).first()
    
    if not regen_request:
        raise HTTPException(status_code=404, detail="Petición no encontrada")
    
    if regen_request.status != 'pending':
        raise HTTPException(status_code=400, detail="Petición ya procesada")
    
    # Marcar como rechazada
    regen_request.status = 'rejected'
    regen_request.processed_at = func.now()
    db.commit()
    
    print(f"❌ Regeneración rechazada: Request {request_id}")
    
    return {
        "message": "Regeneración rechazada",
        "request_id": request_id
    }