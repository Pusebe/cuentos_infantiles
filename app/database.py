from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from .config import settings
from .models import Base
import hashlib

# Crear engine
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def create_tables():
    """Crear todas las tablas"""
    Base.metadata.create_all(bind=engine)
    print("📊 Base de datos inicializada")

def get_db():
    """Dependency para obtener sesión de BD"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def hash_ip(ip: str) -> str:
    """Hash IP para RGPD compliance"""
    return hashlib.sha256(f"{ip}:{settings.secret_key}".encode()).hexdigest()

# Utility functions para rate limiting
def check_rate_limit(db: Session, ip: str, action_type: str, limit_per_day: int) -> bool:
    """
    Verificar si IP puede realizar acción
    Returns True si puede, False si excede límite
    """
    from datetime import datetime, timedelta
    from .models import RateLimitTracker
    
    ip_hash = hash_ip(ip)
    since = datetime.utcnow() - timedelta(days=1)
    
    count = db.query(RateLimitTracker).filter(
        RateLimitTracker.ip_hash == ip_hash,
        RateLimitTracker.action_type == action_type,
        RateLimitTracker.created_at >= since
    ).count()
    
    return count < limit_per_day

def record_action(db: Session, ip: str, action_type: str):
    """Registrar acción para rate limiting"""
    from .models import RateLimitTracker
    
    ip_hash = hash_ip(ip)
    tracker = RateLimitTracker(
        ip_hash=ip_hash,
        action_type=action_type
    )
    db.add(tracker)
    db.commit()

# Utilidades para cleanup
def cleanup_old_uploads():
    """Limpiar fotos temporales > 24h"""
    import os
    from datetime import datetime, timedelta
    from pathlib import Path
    
    cutoff = datetime.now() - timedelta(days=1)
    uploads_dir = settings.uploads_dir
    
    if not uploads_dir.exists():
        return
    
    for file_path in uploads_dir.iterdir():
        if file_path.is_file():
            file_time = datetime.fromtimestamp(file_path.stat().st_mtime)
            if file_time < cutoff:
                try:
                    file_path.unlink()
                    print(f"🗑️ Eliminado: {file_path.name}")
                except Exception as e:
                    print(f"❌ Error eliminando {file_path.name}: {e}")

def get_book_stats(db: Session) -> dict:
    """Estadísticas básicas"""
    from .models import Book
    
    total_books = db.query(Book).count()
    previews = db.query(Book).filter(Book.status == 'preview').count()
    completed = db.query(Book).filter(Book.status == 'completed').count()
    
    return {
        'total_books': total_books,
        'free_previews': previews,
        'completed_books': completed,
        'conversion_rate': (completed / max(total_books, 1)) * 100
    }