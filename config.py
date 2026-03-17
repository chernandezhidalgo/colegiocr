"""
config.py — Configuración centralizada de ColegioCR v3.0.0
Ejecución única diaria a las 6:00 PM (hora CR).
"""
import os
from dotenv import load_dotenv
load_dotenv()

# ── Woot It ────────────────────────────────────────────────────────────────
WOOTIT_USER = os.environ["WOOTIT_USER"]
WOOTIT_PASS = os.environ["WOOTIT_PASS"]
BASE_URL    = "https://www.wootit.com/adventistacademy"

# ── Estudiantes ────────────────────────────────────────────────────────────
HIJO1_LABEL  = "Carlos Emiliano Hernández"
HIJO1_NOMBRE = "Emiliano"
HIJO1_GRADO  = "Sétimo"
HIJO1_ID     = "user213"
HIJO1_QUSUARIO = ""   # Por confirmar — activar Carlos y ver QUSUARIO

HIJO2_LABEL  = "Starling Andrés Hernández"
HIJO2_NOMBRE = "Andrés"
HIJO2_GRADO  = "Octavo"
HIJO2_ID     = "user240"
HIJO2_QUSUARIO = "534"   # ID de sesión real (QUSUARIO) de Starling

# ── Gmail ──────────────────────────────────────────────────────────────────
GMAIL_FROM = "chdezhidalgo@gmail.com"
GMAIL_PASS = os.environ["GMAIL_PASS"]
GMAIL_TO   = ["bromeror@gmail.com", "chernandezhidalgo@gmail.com"]

# ── Supabase ───────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

# ── Anthropic ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
USAR_COMPUTER_USE = bool(ANTHROPIC_API_KEY)
CLAUDE_MODEL      = "claude-opus-4-5"

# ── Vigencia ───────────────────────────────────────────────────────────────
FECHA_FIN_VIGENCIA = "2026-11-20"

# ── Rutas locales ──────────────────────────────────────────────────────────
DIR_ADJUNTOS  = "/tmp/adjuntos"
DIR_LOGS      = "/tmp/logs"
DIR_BASAL     = "/tmp/basal"
TESSERACT_CMD = "/usr/bin/tesseract"
