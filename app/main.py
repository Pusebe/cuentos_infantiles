from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.exception_handlers import http_exception_handler
from sqlalchemy.orm import Session
import json

from .config import settings, setup_directories
from .database import get_db, create_tables, get_book_stats
from .models import Book

# Configuración inicial
setup_directories(settings)
create_tables()

# FastAPI app
app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    version="2.0.0",
    description="Generador de libros infantiles personalizados con IA (Gemini + Gemini Image)"
)

# Static files y templates
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/storage", StaticFiles(directory="storage"), name="storage")

templates = Jinja2Templates(directory="app/templates")

# Incluir routers de API
from .api.books import router as books_router
from .api.admin import router as admin_router

app.include_router(books_router)
app.include_router(admin_router)

# === RUTAS DE PÁGINAS WEB ===

@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request, db: Session = Depends(get_db)):
    """Homepage con formulario de creación"""
    try:
        stats = get_book_stats(db)
        
        context = {
            "request": request,
            "stats": stats,
            "base_price": settings.base_price / 100,
            "price_per_extra_page": settings.price_per_extra_page / 100,
            "default_pages": settings.default_pages,
            "max_pages": 20,
            "gemini_configured": bool(settings.gemini_api_key),
            "ideogram_configured": bool(settings.ideogram_api_key),
            "apis_configured": bool(settings.gemini_api_key)
        }
        
        return templates.TemplateResponse("index.html", context)
        
    except Exception as e:
        print(f"❌ Error en homepage: {e}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Error cargando la página principal",
            "error_code": 500
        })

@app.get("/preview/{book_id}", response_class=HTMLResponse)
async def view_preview(request: Request, book_id: str, db: Session = Depends(get_db)):
    """Ver preview gratuito del libro (portada + info básica)"""
    try:
        book = db.query(Book).filter(Book.id == book_id).first()
        if not book:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": "Libro no encontrado",
                "error_code": 404
            })
        
        if book.status == 'preview_error':
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": f"Error generando el preview: {book.generation_error}",
                "error_code": 500,
                "book": book
            })
        
        story_data = {}
        if book.book_data_json:
            try:
                story_data = json.loads(book.book_data_json)
            except json.JSONDecodeError:
                story_data = {"titulo": book.title or f"El Libro de {book.child_name}"}
        
        context = {
            "request": request,
            "book": book,
            "story_data": story_data,
            "cover_url": f"/storage/previews/{book.cover_preview_path}" if book.cover_preview_path else None,
            "base_price": settings.base_price / 100,
            "price_per_extra_page": settings.price_per_extra_page / 100
        }
        
        return templates.TemplateResponse("preview.html", context)
        
    except Exception as e:
        print(f"❌ Error en view_preview: {e}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Error cargando el preview del libro",
            "error_code": 500
        })

@app.get("/book/{book_id}", response_class=HTMLResponse)
async def view_complete_book(request: Request, book_id: str, db: Session = Depends(get_db)):
    """Ver libro completo (después de pagar)"""
    try:
        book = db.query(Book).filter(Book.id == book_id).first()
        if not book:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": "Libro no encontrado",
                "error_code": 404
            })
        
        if book.status not in ['paid', 'generating', 'completed', 'error']:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": "Este libro debe estar pagado para verlo aquí",
                "error_code": 403
            })
        
        story_data = {}
        if book.book_data_json:
            try:
                story_data = json.loads(book.book_data_json)
            except json.JSONDecodeError:
                story_data = {"titulo": book.title or f"El Libro de {book.child_name}"}
        
        context = {
            "request": request,
            "book": book,
            "story_data": story_data,
            "pdf_url": f"/storage/pdfs/{book.pdf_path}" if book.pdf_path else None
        }
        
        return templates.TemplateResponse("book.html", context)
        
    except Exception as e:
        print(f"❌ Error en view_complete_book: {e}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Error cargando el libro completo",
            "error_code": 500
        })

@app.get("/checkout/{book_id}", response_class=HTMLResponse)
async def checkout_page(request: Request, book_id: str, db: Session = Depends(get_db)):
    """Página de pago (configurar páginas + Stripe)"""
    try:
        book = db.query(Book).filter(Book.id == book_id).first()
        if not book:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": "Libro no encontrado",
                "error_code": 404
            })
        
        if book.status != 'preview_ready':
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": "El preview debe estar listo antes de proceder al pago",
                "error_code": 400,
                "book": book
            })
        
        if book.is_paid:
            if book.status == 'completed':
                return templates.TemplateResponse("book.html", {
                    "request": request,
                    "book": book,
                    "story_data": json.loads(book.book_data_json) if book.book_data_json else {}
                })
            else:
                return templates.TemplateResponse("error.html", {
                    "request": request,
                    "error": "Este libro ya está pagado",
                    "error_code": 400,
                    "book": book
                })
        
        story_data = {}
        if book.book_data_json:
            try:
                story_data = json.loads(book.book_data_json)
            except json.JSONDecodeError:
                story_data = {"titulo": book.title or f"El Libro de {book.child_name}"}
        
        context = {
            "request": request,
            "book": book,
            "story_data": story_data,
            "base_price": settings.base_price / 100,
            "price_per_extra_page": settings.price_per_extra_page / 100,
            "default_pages": settings.default_pages,
            "cover_url": f"/storage/previews/{book.cover_preview_path}" if book.cover_preview_path else None,
            "stripe_publishable_key": settings.stripe_publishable_key or "pk_test_placeholder"
        }
        
        return templates.TemplateResponse("checkout.html", context)
        
    except Exception as e:
        print(f"❌ Error en checkout_page: {e}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Error cargando la página de pago",
            "error_code": 500
        })

@app.get("/admin/regeneration-requests", response_class=HTMLResponse)
async def admin_regeneration_page(request: Request):
    """Panel de administración para aprobar regeneraciones"""
    return templates.TemplateResponse("admin.html", {"request": request})

# === ENDPOINTS DE UTILIDAD ===

@app.get("/health")
async def health_check():
    """Health check endpoint para monitoreo"""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": "2.0.0",
        "gemini_configured": bool(settings.gemini_api_key),
        "database": "connected" if settings.database_url else "not configured"
    }

@app.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """Estadísticas básicas de la aplicación"""
    try:
        stats = get_book_stats(db)
        return stats
    except Exception as e:
        return {"error": str(e)}

# === MANEJO DE ERRORES ===

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    """Manejar errores 404"""
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=404,
            content={"detail": "Endpoint no encontrado"}
        )
    
    return templates.TemplateResponse("error.html", {
        "request": request,
        "error": "Página no encontrada",
        "error_code": 404
    }, status_code=404)

@app.exception_handler(500)
async def server_error_handler(request: Request, exc: Exception):
    """Manejar errores 500"""
    print(f"❌ Error 500: {exc}")
    
    if str(request.url.path).startswith("/api/"):
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno del servidor"}
        )
    
    return templates.TemplateResponse("error.html", {
        "request": request,
        "error": "Error interno del servidor",
        "error_code": 500
    }, status_code=500)

@app.exception_handler(HTTPException)
async def http_exception_handler_custom(request: Request, exc: HTTPException):
    """Manejar errores HTTP generales"""
    if str(request.url.path).startswith("/api/"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )
    
    return templates.TemplateResponse("error.html", {
        "request": request,
        "error": exc.detail,
        "error_code": exc.status_code
    }, status_code=exc.status_code)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug
    )