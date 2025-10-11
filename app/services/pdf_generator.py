"""
Generador de PDFs para libros
"""

from reportlab.lib.pagesizes import inch
from reportlab.pdfgen import canvas
from reportlab.lib.colors import Color
from PIL import Image, ImageDraw, ImageFont
import secrets
from typing import Dict, List, Optional
from ..config import settings
from ..models import Book


class PDFGenerator:
    """Generador de PDFs con imágenes y texto"""
    
    def __init__(self):
        self.page_size = (8.5*inch, 8.5*inch)
        print("📄 PDF Generator inicializado")
    
    async def create_pdf(
        self,
        book: Book,
        story_data: Dict,
        cover_filename: Optional[str],
        page_filenames: List[Optional[str]]
    ) -> Optional[str]:
        """
        Crear PDF con:
        - Portada a página completa
        - 12 páginas con imagen + texto superpuesto
        - Contraportada
        """
        try:
            pdf_filename = f"libro_{book.child_name}_{book.id[:8]}.pdf"
            pdf_path = settings.pdfs_dir / pdf_filename
            
            c = canvas.Canvas(str(pdf_path), pagesize=self.page_size)
            width, height = self.page_size
            
            # 1. PORTADA a página completa
            if cover_filename:
                cover_path = settings.previews_dir / cover_filename
                if cover_path.exists():
                    c.drawImage(
                        str(cover_path), 
                        0, 0, 
                        width=width, 
                        height=height, 
                        preserveAspectRatio=True, 
                        anchor='c'
                    )
                    c.showPage()
            
            # 2. PÁGINAS con imagen + texto superpuesto
            for i, page_data in enumerate(story_data['paginas'], 1):
                page_filename = page_filenames[i-1] if i-1 < len(page_filenames) else None
                
                # Dibujar imagen de fondo
                if page_filename:
                    page_path = settings.books_dir / page_filename
                    if page_path.exists():
                        c.drawImage(
                            str(page_path), 
                            0, 0, 
                            width=width, 
                            height=height, 
                            preserveAspectRatio=True, 
                            anchor='c'
                        )
                
                # Zona de texto con fondo semi-transparente
                text_height = 2*inch
                c.setFillColor(Color(0, 0, 0, alpha=0.5))
                c.rect(0, 0, width, text_height, fill=1, stroke=0)
                
                # Texto en blanco con ajuste automático
                texto = page_data['texto']
                max_width = width - inch
                max_lines = 7
                
                font_size = self._get_optimal_font_size(
                    c, texto, max_width, text_height - inch, max_lines
                )
                
                c.setFillColor(Color(1, 1, 1, alpha=1))
                c.setFont("Helvetica-Bold", font_size)
                
                # Dividir texto en líneas
                lines = self._wrap_text(c, texto, max_width, "Helvetica-Bold", font_size)
                
                # Dibujar líneas
                y_start = text_height - 0.5*inch
                line_height = font_size + 4
                x_left = 0.5*inch
                
                for line in lines:
                    c.drawString(x_left, y_start, line)
                    y_start -= line_height
                
                c.showPage()
            
            # 3. CONTRAPORTADA
            await self._add_back_cover(c, story_data, width, height)
            c.showPage()
            
            c.save()
            print(f"📄 PDF creado: {pdf_filename} ({len(story_data['paginas']) + 2} páginas totales)")
            return pdf_filename
            
        except Exception as e:
            print(f"❌ Error creando PDF: {e}")
            return None
    
    def _get_optimal_font_size(
        self, 
        canvas_obj, 
        text: str, 
        max_width: float, 
        max_height: float, 
        max_lines: int
    ) -> int:
        """Calcular el tamaño de fuente óptimo"""
        for font_size in [18, 16, 14, 12]:
            lines = self._wrap_text(canvas_obj, text, max_width, "Helvetica-Bold", font_size)
            line_height = font_size + 4
            total_height = len(lines) * line_height
            
            if len(lines) <= max_lines and total_height <= max_height:
                return font_size
        
        return 12
    
    def _wrap_text(
        self, 
        canvas_obj, 
        text: str, 
        max_width: float, 
        font_name: str, 
        font_size: int
    ) -> List[str]:
        """Dividir texto en líneas"""
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            test_line = current_line + " " + word if current_line else word
            if canvas_obj.stringWidth(test_line, font_name, font_size) < max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        
        if current_line:
            lines.append(current_line)
        
        return lines
    
    async def _add_back_cover(self, canvas_obj, story_data: Dict, width: float, height: float):
        """Añadir contraportada"""
        try:
            # Crear imagen para contraportada
            img_width = int(width * 72 / inch)
            img_height = int(height * 72 / inch)
            
            img = Image.new('RGB', (img_width, img_height))
            draw = ImageDraw.Draw(img)
            
            # Fondo degradado
            for i in range(img_height):
                ratio = i / img_height
                r = int(200 + (150 - 200) * ratio)
                g = int(220 + (200 - 220) * ratio)
                b = int(255 + (230 - 255) * ratio)
                draw.rectangle([(0, i), (img_width, i+1)], fill=(r, g, b))
            
            # Fuentes
            try:
                title_font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60
                )
                text_font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32
                )
            except:
                title_font = ImageFont.load_default()
                text_font = ImageFont.load_default()
            
            # Título
            titulo = story_data.get('titulo', 'Un Libro Mágico')
            title_bbox = draw.textbbox((0, 0), titulo, font=title_font)
            title_width = title_bbox[2] - title_bbox[0]
            title_x = (img_width - title_width) // 2
            title_y = 100
            
            draw.text((title_x, title_y), titulo, fill=(50, 50, 100), font=title_font)
            
            # Resumen
            resumen = story_data.get('resumen', 'Una aventura maravillosa')
            
            words = resumen.split()
            lines = []
            current_line = ""
            max_width = img_width - 200
            
            for word in words:
                test_line = current_line + " " + word if current_line else word
                test_bbox = draw.textbbox((0, 0), test_line, font=text_font)
                test_width = test_bbox[2] - test_bbox[0]
                
                if test_width < max_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            
            if current_line:
                lines.append(current_line)
            
            # Dibujar resumen
            y_pos = img_height // 2 - (len(lines) * 40) // 2
            for line in lines:
                line_bbox = draw.textbbox((0, 0), line, font=text_font)
                line_width = line_bbox[2] - line_bbox[0]
                line_x = (img_width - line_width) // 2
                draw.text((line_x, y_pos), line, fill=(70, 70, 70), font=text_font)
                y_pos += 45
            
            # Guardar temporal
            temp_back_cover = settings.pdfs_dir / f"temp_back_{secrets.token_urlsafe(8)}.png"
            img.save(temp_back_cover)
            
            # Dibujar en canvas
            canvas_obj.drawImage(str(temp_back_cover), 0, 0, width=width, height=height)
            
            # Limpiar temporal
            try:
                temp_back_cover.unlink(missing_ok=True)
            except:
                pass
            
            print("✅ Contraportada añadida")
            
        except Exception as e:
            print(f"❌ Error creando contraportada: {e}")
            # Contraportada simple de fallback
            canvas_obj.setFillColor(Color(0.85, 0.9, 1.0))
            canvas_obj.rect(0, 0, width, height, fill=1, stroke=0)
            canvas_obj.setFillColor(Color(0.2, 0.2, 0.4))
            canvas_obj.setFont("Helvetica-Bold", 48)
            canvas_obj.drawCentredString(
                width/2, 
                height/2, 
                story_data.get('titulo', 'Un Libro Mágico')
            )