"""
Módulo de procesamiento de adjuntos: PDFs e imágenes.
Extrae texto con pdfplumber y OCR Tesseract; usa Claude Vision como respaldo.
"""

import base64
import logging
import os
from pathlib import Path

import anthropic
import pdfplumber
import pytesseract
import requests
from PIL import Image

import config

pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD
os.makedirs(config.DIR_ADJUNTOS, exist_ok=True)
logger = logging.getLogger(__name__)


def descargar_adjunto(url: str, nombre: str, cookies: dict) -> str | None:
    try:
        resp = requests.get(url, cookies=cookies, timeout=30)
        ruta = Path(config.DIR_ADJUNTOS) / nombre
        ruta.write_bytes(resp.content)
        logger.info(f"Adjunto descargado: {ruta}")
        return str(ruta)
    except Exception as e:
        logger.error(f"Error descargando adjunto {url}: {e}")
        return None


def leer_pdf(ruta: str) -> str:
    try:
        texto = []
        with pdfplumber.open(ruta) as pdf:
            for i, pagina in enumerate(pdf.pages):
                t = pagina.extract_text()
                if t:
                    texto.append(f"[Página {i+1}]\n{t}")
                for img in pagina.images:
                    try:
                        crop = pagina.crop((img['x0'], img['top'], img['x1'], img['bottom']))
                        img_pil = crop.to_image(resolution=200).original
                        ocr_txt = pytesseract.image_to_string(img_pil, lang='spa')
                        if ocr_txt.strip():
                            texto.append(f"[Imagen en página {i+1}]:\n{ocr_txt}")
                    except Exception:
                        pass
        resultado = "\n".join(texto)
        return resultado if resultado.strip() else '[PDF sin texto extraíble]'
    except Exception as e:
        logger.error(f"Error leyendo PDF {ruta}: {e}")
        return f'[Error al procesar PDF: {e}]'


def _analizar_imagen_con_claude(ruta: str) -> str:
    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        ext = Path(ruta).suffix.lower()
        media_map = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp'
        }
        media_type = media_map.get(ext, 'image/png')
        with open(ruta, 'rb') as f:
            img_b64 = base64.standard_b64encode(f.read()).decode('utf-8')
        resp = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{'role': 'user', 'content': [
                {'type': 'image', 'source': {'type': 'base64',
                 'media_type': media_type, 'data': img_b64}},
                {'type': 'text', 'text': (
                    "Esta imagen es un adjunto de un mensaje del portal educativo "
                    "de un colegio en Costa Rica. Describe en español de forma estructurada:\n"
                    "1. ¿Qué tipo de documento o aviso es?\n"
                    "2. ¿Cuál es el mensaje o información principal?\n"
                    "3. ¿Hay fechas, montos, materias o nombres importantes?\n"
                    "4. ¿Requiere alguna acción del padre de familia?\n"
                    "Sé conciso pero completo."
                )}
            ]}]
        )
        return resp.content[0].text
    except Exception as e:
        logger.warning(f"Claude Vision falló para {ruta}: {e}")
        return '[Imagen no procesable automáticamente]'


def leer_imagen(ruta: str) -> str:
    try:
        img = Image.open(ruta)
        texto_ocr = pytesseract.image_to_string(img, lang='spa+eng').strip()
        if len(texto_ocr) < 50 and config.USAR_COMPUTER_USE:
            texto_ocr = _analizar_imagen_con_claude(ruta)
        return texto_ocr if texto_ocr else '[Imagen sin texto legible]'
    except Exception as e:
        logger.error(f"Error procesando imagen {ruta}: {e}")
        return f'[Error al procesar imagen: {e}]'


def procesar_adjunto(url: str, nombre: str, cookies: dict) -> dict:
    ruta = descargar_adjunto(url, nombre, cookies)
    if not ruta:
        return {'ruta': None, 'contenido': '[No se pudo descargar]', 'nombre': nombre}
    ext = Path(ruta).suffix.lower()
    if ext == '.pdf':
        contenido = leer_pdf(ruta)
    elif ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff']:
        contenido = leer_imagen(ruta)
    else:
        contenido = f'[Formato no soportado: {ext}]'
    return {'ruta': ruta, 'contenido': contenido, 'nombre': nombre}
