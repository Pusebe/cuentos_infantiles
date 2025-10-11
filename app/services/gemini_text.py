"""
Servicio para Gemini - Generación de historias con vision
"""

from google import genai
from PIL import Image
import json
import asyncio
from typing import Dict
from ..config import settings


class GeminiTextService:
    """Servicio para generación de historias con Gemini"""
    
    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY no configurada")
        
        self.client = genai.Client(api_key=settings.gemini_api_key)
        print("🤖 Gemini Text Service configurado")
    
    async def generate_minimal_story(
        self, 
        photo_path: str, 
        child_name: str, 
        age: int, 
        description: str
    ) -> Dict:
        """
        Genera historia MÍNIMA para preview rápido:
        - Solo título, tema, resumen
        - Descripción básica del protagonista
        - SIN páginas detalladas, SIN personajes secundarios
        """
        
        img = Image.open(photo_path)
        
        prompt = f"""Crea una idea BÁSICA de cuento infantil basado en la foto y en los intereses.

INFORMACIÓN:
- Nombre: {child_name}
- Edad: {age} años
- Intereses: {description or 'aventuras mágicas'}

GENERA SOLO:
- Un título atractivo
- Un tema general (aventura, fantasía, amistad, etc.)
- Un resumen breve de 2-3 líneas
- Descripción física DETALLADA del protagonista de la foto

JSON MÍNIMO:
{{
    "titulo": "Título creativo del libro",
    "tema": "aventura/fantasía/amistad/etc",
    "resumen": "Resumen breve de la aventura",
    "mundo_descripcion": "Descripción del mundo/escenario donde ocurre (bosque mágico, espacio, ciudad fantástica, etc.)",
    "protagonista": {{
        "nombre": "{child_name}",
        "descripcion_fisica": "Descripción DETALLADA de la apariencia del niño/a en la foto (color de pelo, forma de cara, rasgos únicos, ropa si es visible)"
    }}
}}

IMPORTANTE: Solo genera esta información básica, NO generes páginas ni personajes secundarios."""
        
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=settings.gemini_model,
                contents=[prompt, img]
            )
            
            story_data = self._parse_minimal_response(response.text, child_name)
            
            print(f"📖 Historia mínima generada: '{story_data['titulo']}'")
            return story_data
            
        except Exception as e:
            print(f"❌ Error generando historia mínima: {e}")
            return self._fallback_minimal_story(child_name, age)
    
    async def extend_full_story(
        self,
        minimal_story: Dict,
        num_pages: int = 12
    ) -> Dict:
        """
        Extiende la historia mínima a historia COMPLETA con:
        - 12 páginas detalladas
        - Personajes secundarios con IDs
        - Objetos importantes con IDs
        - Escenarios con IDs
        """
        
        prompt = f"""Extiende esta idea de cuento en una historia COMPLETA de {num_pages} páginas.

HISTORIA BASE:
- Título: {minimal_story['titulo']}
- Tema: {minimal_story['tema']}
- Resumen: {minimal_story['resumen']}
- Mundo: {minimal_story.get('mundo_descripcion', 'mundo mágico')}
- Protagonista: {minimal_story['protagonista']['nombre']} - {minimal_story['protagonista']['descripcion_fisica']}

GENERA HISTORIA COMPLETA:
- EXACTAMENTE {num_pages} páginas
- Máximo 3 personajes (incluido protagonista)
- Máximo 3 objetos importantes
- Máximo 3 escenarios diferentes
- Cada página: máximo 50 palabras

DESCRIPCIONES MUY DETALLADAS:
- Cada personaje: descripción física completa (ropa, color de pelo, rasgos)
- Cada objeto: forma, color, tamaño, textura
- Cada escenario: ambiente, colores dominantes, elementos principales, atmósfera
- Cada página: descripción VISUAL DETALLADA de la escena, posiciones de elementos

JSON COMPLETO CON IDS NUMÉRICOS:
{{
    "titulo": "{minimal_story['titulo']}",
    "tema": "{minimal_story['tema']}",
    "resumen": "{minimal_story['resumen']}",
    "leccion": "Qué aprenderá el niño",
    "personajes_principales": [
        {{
            "id": 1,
            "nombre": "{minimal_story['protagonista']['nombre']}",
            "descripcion": "{minimal_story['protagonista']['descripcion_fisica']}"
        }},
        {{
            "id": 2,
            "nombre": "Nombre personaje secundario",
            "descripcion": "Descripción FÍSICA DETALLADA completa"
        }}
    ],
    "objetos_importantes": [
        {{
            "id": 1,
            "nombre": "Nombre del objeto",
            "descripcion": "Descripción DETALLADA (forma, color, tamaño, textura)"
        }}
    ],
    "escenarios": [
        {{
            "id": 1,
            "nombre": "Nombre del escenario",
            "descripcion": "Descripción DETALLADA (colores, iluminación, elementos, atmósfera)"
        }}
    ],
    "paginas": [
        {{
            "numero": 1,
            "texto": "Texto de la página (máximo 50 palabras)",
            "escena_detallada": "Descripción VISUAL DETALLADA: qué ilustrar, dónde está cada elemento, qué hacen, posiciones relativas, expresiones",
            "personajes_ids": [1],
            "objetos_ids": [1],
            "escenario_id": 1
        }}
    ]
}}

CRÍTICO: Las descripciones deben ser TAN detalladas que un ilustrador pueda dibujar exactamente lo mismo."""
        
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=settings.gemini_model,
                contents=[prompt]
            )
            
            story_data = self._parse_full_response(response.text, minimal_story, num_pages)
            
            print(f"📖 Historia completa generada con {len(story_data['paginas'])} páginas")
            return story_data
            
        except Exception as e:
            print(f"❌ Error extendiendo historia: {e}")
            return self._fallback_full_story(minimal_story, num_pages)
    
    def _parse_minimal_response(self, response_text: str, child_name: str) -> Dict:
        """Parsear respuesta mínima"""
        try:
            clean_text = response_text.strip()
            if clean_text.startswith('```json'):
                clean_text = clean_text[7:]
            if clean_text.startswith('```'):
                clean_text = clean_text[3:]
            if clean_text.endswith('```'):
                clean_text = clean_text[:-3]
            
            data = json.loads(clean_text.strip())
            data['child_name'] = child_name
            
            # Validar estructura mínima
            if 'titulo' not in data:
                data['titulo'] = f"Las Aventuras de {child_name}"
            if 'tema' not in data:
                data['tema'] = "aventura"
            if 'resumen' not in data:
                data['resumen'] = f"Una historia mágica sobre {child_name}"
            if 'mundo_descripcion' not in data:
                data['mundo_descripcion'] = "Un mundo mágico lleno de aventuras"
            if 'protagonista' not in data:
                data['protagonista'] = {
                    "nombre": child_name,
                    "descripcion_fisica": f"{child_name}, el protagonista"
                }
            
            return data
            
        except Exception as e:
            print(f"❌ Error parseando historia mínima: {e}")
            raise e
    
    def _parse_full_response(self, response_text: str, minimal_story: Dict, num_pages: int) -> Dict:
        """Parsear respuesta completa"""
        try:
            clean_text = response_text.strip()
            if clean_text.startswith('```json'):
                clean_text = clean_text[7:]
            if clean_text.startswith('```'):
                clean_text = clean_text[3:]
            if clean_text.endswith('```'):
                clean_text = clean_text[:-3]
            
            data = json.loads(clean_text.strip())
            data['child_name'] = minimal_story['child_name']
            
            # Asegurar estructura con IDs numéricos
            if 'personajes_principales' not in data:
                data['personajes_principales'] = [
                    {
                        "id": 1,
                        "nombre": minimal_story['protagonista']['nombre'],
                        "descripcion": minimal_story['protagonista']['descripcion_fisica']
                    }
                ]
            
            if 'objetos_importantes' not in data:
                data['objetos_importantes'] = []
            
            if 'escenarios' not in data:
                data['escenarios'] = [
                    {
                        "id": 1,
                        "nombre": "Escenario principal",
                        "descripcion": minimal_story.get('mundo_descripcion', 'Mundo mágico')
                    }
                ]
            
            # Limitar y numerar
            data['personajes_principales'] = data['personajes_principales'][:3]
            for i, p in enumerate(data['personajes_principales'], 1):
                p['id'] = i
            
            data['objetos_importantes'] = data['objetos_importantes'][:3]
            for i, o in enumerate(data['objetos_importantes'], 1):
                o['id'] = i
            
            data['escenarios'] = data['escenarios'][:3]
            for i, e in enumerate(data['escenarios'], 1):
                e['id'] = i
            
            # Ajustar páginas
            if len(data['paginas']) != num_pages:
                print(f"⚠️ Ajustando páginas: {len(data['paginas'])} → {num_pages}")
                if len(data['paginas']) > num_pages:
                    data['paginas'] = data['paginas'][:num_pages]
                else:
                    while len(data['paginas']) < num_pages:
                        data['paginas'].append({
                            "numero": len(data['paginas']) + 1,
                            "texto": f"{minimal_story['protagonista']['nombre']} continuó su aventura.",
                            "escena_detallada": "Escena de aventura",
                            "personajes_ids": [1],
                            "objetos_ids": [],
                            "escenario_id": 1
                        })
            
            return data
            
        except Exception as e:
            print(f"❌ Error parseando historia completa: {e}")
            raise e
    
    def _fallback_minimal_story(self, child_name: str, age: int) -> Dict:
        """Historia mínima de respaldo"""
        return {
            "child_name": child_name,
            "titulo": f"Las Aventuras de {child_name}",
            "tema": "aventura",
            "resumen": f"Una historia mágica donde {child_name} vive una gran aventura",
            "mundo_descripcion": "Un mundo mágico lleno de sorpresas",
            "protagonista": {
                "nombre": child_name,
                "descripcion_fisica": f"{child_name}, el valiente protagonista"
            }
        }
    
    def _fallback_full_story(self, minimal_story: Dict, num_pages: int) -> Dict:
        """Historia completa de respaldo"""
        pages = []
        child_name = minimal_story['protagonista']['nombre']
        
        for i in range(1, num_pages + 1):
            pages.append({
                "numero": i,
                "texto": f"{child_name} vivió una gran aventura.",
                "escena_detallada": f"{child_name} en una escena emocionante",
                "personajes_ids": [1],
                "objetos_ids": [],
                "escenario_id": 1
            })
        
        return {
            "child_name": minimal_story['child_name'],
            "titulo": minimal_story['titulo'],
            "tema": minimal_story['tema'],
            "resumen": minimal_story['resumen'],
            "leccion": "Valentía y amistad",
            "personajes_principales": [
                {
                    "id": 1,
                    "nombre": child_name,
                    "descripcion": minimal_story['protagonista']['descripcion_fisica']
                }
            ],
            "objetos_importantes": [],
            "escenarios": [
                {
                    "id": 1,
                    "nombre": "Mundo mágico",
                    "descripcion": minimal_story.get('mundo_descripcion', 'Un mundo mágico')
                }
            ],
            "paginas": pages
        }