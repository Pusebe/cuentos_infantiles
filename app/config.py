import os
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App
    app_name: str = "Generador de Libros Infantiles"
    debug: bool = False
    secret_key: str = "fallback-secret-key-change-in-production"
    
    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"  # GPT-5 nano para texto
    openai_image_model: str = "dall-e-3"  # DALL-E 3 para imágenes
    openai_image_quality: str = "standard"  # standard o hd para DALL-E 3
    openai_image_size: str = "1024x1024"
    
    # Stripe (para futuro uso)
    stripe_publishable_key: str = ""
    stripe_secret_key: str = ""
    
    # Base de datos
    database_url: str = "sqlite:///./books.db"
    
    # Archivos
    max_file_size: int = 16 * 1024 * 1024  # 16MB
    allowed_extensions: set = {"png", "jpg", "jpeg", "gif", "webp"}
    
    # Paths
    base_dir: Path = Path(__file__).parent.parent
    storage_dir: Path = base_dir / "storage"
    uploads_dir: Path = storage_dir / "uploads"
    books_dir: Path = storage_dir / "books"
    previews_dir: Path = storage_dir / "previews"
    pdfs_dir: Path = storage_dir / "pdfs"
    
    # Pricing (en céntimos para evitar decimales)
    base_price: int = 1000  # 10€ = 1000 céntimos
    price_per_extra_page: int = 80  # 0.80€ = 80 céntimos
    default_pages: int = 6
    
    # Rate limiting
    free_previews_per_ip_per_day: int = 999
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # ESTO SOLUCIONA EL ERROR: ignora variables extra del .env

# Crear directorios necesarios
def setup_directories(settings: Settings):
    """Crear todos los directorios necesarios"""
    directories = [
        settings.storage_dir,
        settings.uploads_dir,
        settings.books_dir,
        settings.previews_dir,
        settings.pdfs_dir,
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    
    print(f"📁 Directorios creados en: {settings.storage_dir}")

settings = Settings()