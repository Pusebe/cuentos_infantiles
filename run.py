#!/usr/bin/env python3
"""
Punto de entrada para la aplicación
Ejecutar: python run.py
"""

import uvicorn
from app.config import settings
from app.main import app

def main():
    print("🚀 Iniciando Generador de Libros Infantiles V2...")
    print(f"📍 URL: http://localhost:8000")
    print(f"🐛 Debug mode: {settings.debug}")
    
    if not settings.openai_api_key:
        print("⚠️  ADVERTENCIA: OPENAI_API_KEY no configurada")
        print("   Configure su API key en el archivo .env")
    else:
        print("✅ OpenAI API configurada")
    
    print("-" * 50)
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=5001,
        reload=settings.debug,
        log_level="info" if not settings.debug else "debug"
    )

if __name__ == "__main__":
    main()