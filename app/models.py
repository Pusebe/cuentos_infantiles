from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from decimal import Decimal
from datetime import datetime
import secrets

Base = declarative_base()

class Book(Base):
    __tablename__ = "books"
    
    # ID único y seguro para URLs
    id = Column(String(32), primary_key=True, default=lambda: secrets.token_urlsafe(24))
    
    # Información del niño
    child_name = Column(String(100), nullable=False)
    child_age = Column(Integer, nullable=False)
    child_description = Column(Text)
    
    # Configuración del libro
    total_pages = Column(Integer, default=12)  # Ahora fijo a 12
    story_theme = Column(String(200))
    title = Column(String(200))
    
    # Estados del proceso
    status = Column(String(20), default='preview')  # preview, paid, generating, completed, error
    current_step = Column(String(200))  # NUEVO: Paso actual detallado
    progress_percentage = Column(Integer, default=0)  # NUEVO: 0-100
    
    # Archivos generados
    original_photo_path = Column(String(500))
    cover_preview_path = Column(String(500))  # Portada gratuita
    book_data_json = Column(Text)  # Historia completa + metadatos
    pdf_path = Column(String(500))  # Libro completado
    
    # Pago (futuro Stripe)
    payment_intent_id = Column(String(100))
    amount_paid = Column(Integer)  # En céntimos (evitamos decimales)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    paid_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    
    # Metadata
    generation_error = Column(Text)
    ip_hash = Column(String(64))  # Para rate limiting
    
    def __repr__(self):
        return f"<Book {self.id}: {self.child_name} ({self.status})>"
    
    @property
    def total_price_cents(self):
        """Calcular precio total en céntimos"""
        from .config import settings
        base = settings.base_price
        extra_pages = max(0, self.total_pages - settings.default_pages)
        extra_cost = extra_pages * settings.price_per_extra_page
        return base + extra_cost
    
    @property
    def total_price_euros(self):
        """Precio en euros para mostrar al usuario"""
        return self.total_price_cents / 100
    
    @property
    def is_free_preview(self):
        return self.status == 'preview'
    
    @property
    def is_paid(self):
        return self.status in ['paid', 'generating', 'completed']
    
    @property
    def is_ready(self):
        return self.status == 'completed' and self.pdf_path

class RateLimitTracker(Base):
    __tablename__ = "rate_limits"
    
    id = Column(Integer, primary_key=True)
    ip_hash = Column(String(64), nullable=False)
    action_type = Column(String(50), nullable=False)  # 'free_preview', 'upload', 'regenerate_preview'
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f"<RateLimit {self.ip_hash[:8]}... {self.action_type}>"

class RegenerationRequest(Base):
    """NUEVO: Peticiones de regeneración de páginas"""
    __tablename__ = "regeneration_requests"
    
    id = Column(Integer, primary_key=True)
    book_id = Column(String(32), nullable=False)
    page_number = Column(Integer, nullable=False)
    reason = Column(Text)
    status = Column(String(20), default='pending')  # pending, approved, rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True))
    
    def __repr__(self):
        return f"<RegenerationRequest {self.id}: Page {self.page_number} of Book {self.book_id[:8]}>"

# Pydantic models para API responses
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class BookBase(BaseModel):
    child_name: str
    child_age: int
    child_description: Optional[str] = None
    total_pages: int = 12

class BookCreate(BookBase):
    pass

class BookResponse(BookBase):
    id: str
    status: str
    current_step: Optional[str]
    progress_percentage: int
    title: Optional[str]
    story_theme: Optional[str]
    total_price_euros: float
    created_at: datetime
    cover_preview_path: Optional[str]
    pdf_path: Optional[str]
    
    class Config:
        from_attributes = True

class BookPreview(BaseModel):
    id: str
    child_name: str
    child_age: int
    title: str
    cover_preview_path: str
    story_preview: str  # Primera línea de la historia
    
    class Config:
        from_attributes = True