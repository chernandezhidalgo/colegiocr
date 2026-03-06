"""
Clasificador de mensajes del portal educativo.
Determina categoría, urgencia y si requiere acción del padre.
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ_CR = ZoneInfo("America/Costa_Rica")

# Palabras clave por categoría
CATEGORIAS = {
    "cobro": [
        "pago", "cuota", "cancelar", "monto", "colones", "factura",
        "adeudo", "mora", "deuda", "matrícula", "mensualidad"
    ],
    "autorizacion": [
        "autorización", "autorizar", "firma", "firmar", "permiso",
        "consentimiento", "formulario", "devolver firmado"
    ],
    "disciplinario": [
        "anotación", "disciplina", "conducta", "comportamiento",
        "sanción", "suspensión", "llamada de atención", "falta"
    ],
    "actividad": [
        "paseo", "excursión", "actividad", "evento", "visita",
        "presentación", "acto", "graduación", "deporte", "competencia"
    ],
    "evento": [
        "reunión", "asamblea", "entrega", "ceremonia", "feriado",
        "asueto", "no hay clases", "suspensión de lecciones"
    ],
    "circular": [
        "circular", "comunicado", "aviso", "información general",
        "estimados padres", "recordatorio"
    ],
}

PALABRAS_URGENCIA_ALTA = [
    "urgente", "inmediato", "hoy", "mañana", "vence", "vencimiento",
    "último día", "plazo", "antes del", "a más tardar", "obligatorio"
]

def clasificar_mensaje(asunto: str, cuerpo: str) -> dict:
    """
    Clasifica un mensaje y retorna categoría, urgencia y si requiere acción.
    """
    texto = f"{asunto} {cuerpo}".lower()

    # Determinar categoría
    categoria = "circular"
    max_matches = 0
    for cat, palabras in CATEGORIAS.items():
        matches = sum(1 for p in palabras if p in texto)
        if matches > max_matches:
            max_matches = matches
            categoria = cat

    # Determinar si requiere acción
    requiere_accion = categoria in ("cobro", "autorizacion", "disciplinario")

    # Determinar urgencia
    tiene_urgencia_alta = any(p in texto for p in PALABRAS_URGENCIA_ALTA)
    if categoria == "disciplinario" or tiene_urgencia_alta:
        urgencia = "alta"
    elif categoria in ("cobro", "autorizacion", "actividad"):
        urgencia = "media"
    else:
        urgencia = "baja"

    # Extraer fecha límite si existe
    fecha_limite = _extraer_fecha_limite(texto)

    # Extraer monto si existe
    monto = _extraer_monto(texto)

    return {
        "categoria":       categoria,
        "urgencia":        urgencia,
        "requiere_accion": requiere_accion,
        "fecha_limite":    fecha_limite,
        "monto":           monto,
    }


def _extraer_fecha_limite(texto: str) -> str:
    """Extrae fecha límite mencionada en el texto."""
    patrones = [
        r"antes del (\d{1,2} de \w+ de \d{4})",
        r"a más tardar el (\d{1,2} de \w+ de \d{4})",
        r"vence el (\d{1,2} de \w+ de \d{4})",
        r"hasta el (\d{1,2}/\d{1,2}/\d{4})",
        r"fecha límite[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
    ]
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extraer_monto(texto: str) -> str:
    """Extrae montos en colones o dólares."""
    patrones = [
        r"₡\s?([\d,\.]+)",
        r"(\d[\d,\.]+)\s*colones",
        r"\$\s?([\d,\.]+)",
    ]
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return None


def emoji_categoria(categoria: str) -> str:
    emojis = {
        "cobro":         "💰",
        "autorizacion":  "✍️",
        "disciplinario": "⚠️",
        "actividad":     "🎒",
        "evento":        "📅",
        "circular":      "📢",
    }
    return emojis.get(categoria, "📋")


def emoji_urgencia(urgencia: str) -> str:
    return {"alta": "🔴", "media": "🟡", "baja": "🟢"}.get(urgencia, "⚪")
