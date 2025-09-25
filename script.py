#!/usr/bin/env python3
"""
Script para crear la estructura completa del proyecto
Ejecutar: python setup_project.py
"""

import os
from pathlib import Path

def create_file(path: Path, content: str = ""):
    """Crear archivo con contenido básico"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"📄 Creado: {path}")

def create_dir(path: Path):
    """Crear directorio"""
    path.mkdir(parents=True, exist_ok=True)
    print(f"📁 Creado: {path}")

def setup_project_structure():
    """Crear toda la estructura del proyecto"""
    
    print("🚀 Creando estructura del proyecto...")
    
    base_dir = Path(".")
    
    # Directorios principales
    directories = [
        "app",
        "app/api",
        "app/templates", 
        "static/css",
        "static/js",
        "static/images",
        "storage/uploads",
        "storage/books", 
        "storage/previews",
        "storage/pdfs"
    ]
    
    for dir_path in directories:
        create_dir(base_dir / dir_path)
    
    # Archivos Python principales
    python_files = {
        "app/__init__.py": "",
        "app/main.py": "# FastAPI main application",
        "app/config.py": "# Configuration settings",
        "app/models.py": "# SQLAlchemy models", 
        "app/database.py": "# Database connection and utilities",
        "app/services.py": "# OpenAI and business logic services",
        
        # API endpoints separados
        "app/api/__init__.py": "",
        "app/api/books.py": "# Book creation and management endpoints",
        "app/api/payments.py": "# Stripe payment endpoints", 
        "app/api/preview.py": "# Free preview endpoints",
        
        # Punto de entrada
        "run.py": "# Application entry point"
    }
    
    for file_path, content in python_files.items():
        create_file(base_dir / file_path, content)
    
    # Templates HTML
    html_files = {
        "app/templates/base.html": "<!-- Base template -->",
        "app/templates/index.html": "<!-- Homepage -->",
        "app/templates/preview.html": "<!-- Free preview page -->", 
        "app/templates/checkout.html": "<!-- Payment page -->",
        "app/templates/book.html": "<!-- Complete book viewer -->",
        "app/templates/error.html": "<!-- Error page -->"
    }
    
    for file_path, content in html_files.items():
        create_file(base_dir / file_path, content)
    
    # Static files
    static_files = {
        "static/css/style.css": "/* Main stylesheet */",
        "static/js/main.js": "// Main JavaScript",
        "static/js/checkout.js": "// Checkout functionality", 
        "static/js/book-viewer.js": "// Book viewer functionality"
    }
    
    for file_path, content in static_files.items():
        create_file(base_dir / file_path, content)
    
    # Archivos de configuración
    config_files = {
        "requirements.txt": """# Requirements will be added here""",
        ".env.example": """# Environment variables example
OPENAI_API_KEY=your_openai_api_key_here
SECRET_KEY=your_secret_key_here
DEBUG=True
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_SECRET_KEY=sk_test_...""",
        ".gitignore": """.env
__pycache__/
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
.venv/
pip-log.txt
pip-delete-this-directory.txt
.tox/
.coverage
.pytest_cache/
htmlcov/
.DS_Store
storage/uploads/*
storage/books/*
storage/previews/*
storage/pdfs/*
*.db
*.sqlite3""",
        "README.md": """# Generador de Libros Infantiles V2

Aplicación web que genera libros infantiles personalizados usando IA.

## Setup

1. `python setup_project.py` (crear estructura)
2. `pip install -r requirements.txt`
3. Copiar `.env.example` a `.env` y configurar
4. `python run.py`

## Estructura

- `app/` - Aplicación principal
- `static/` - CSS, JS, imágenes
- `storage/` - Archivos generados
- `requirements.txt` - Dependencias""",
        "Dockerfile": """# Docker configuration (for future use)
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]""",
        "docker-compose.yml": """# Docker compose (for future use)
version: '3.8'
services:
  app:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./storage:/app/storage
    environment:
      - DEBUG=True"""
    }
    
    for file_path, content in config_files.items():
        create_file(base_dir / file_path, content)
    
    # Crear archivos .gitkeep para directorios vacíos
    gitkeep_dirs = [
        "storage/uploads",
        "storage/books",
        "storage/previews", 
        "storage/pdfs",
        "static/images"
    ]
    
    for dir_path in gitkeep_dirs:
        create_file(base_dir / dir_path / ".gitkeep", "")
    
    print("\n✅ Estructura del proyecto creada exitosamente!")
    print("\nPróximos pasos:")
    print("1. cd libro_infantil_v2")
    print("2. python -m venv venv")
    print("3. source venv/bin/activate  # (Linux/Mac) o venv\\Scripts\\activate  # (Windows)")
    print("4. pip install -r requirements.txt")
    print("5. cp .env.example .env")
    print("6. Editar .env con tus API keys")
    print("7. python run.py")
    
    # Mostrar estructura creada
    print("\n📁 Estructura creada:")
    print("libro_infantil_v2/")
    for root, dirs, files in os.walk("."):
        # Filtrar directorios ocultos
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        level = root.replace(".", "").count(os.sep)
        indent = " " * 2 * level
        print(f"{indent}├── {os.path.basename(root)}/")
        
        subindent = " " * 2 * (level + 1)
        for file in files:
            if not file.startswith('.') or file in ['.env.example', '.gitignore']:
                print(f"{subindent}├── {file}")

if __name__ == "__main__":
    setup_project_structure()