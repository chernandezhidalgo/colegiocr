import os
from dotenv import load_dotenv
load_dotenv()

# ── Woot It ──────────────────────────────────
WOOTIT_USER  = os.environ["WOOTIT_USER"]
WOOTIT_PASS  = os.environ["WOOTIT_PASS"]
BASE_URL     = "https://www.wootit.com/adventistacademy"

# ── Estudiantes ──────────────────────────────
HIJO1_LABEL  = "Carlos Emiliano Hernández"
HIJO1_GRADO  = "Sétimo"
HIJO1_ID     = "user213"

HIJO2_LABEL  = "Starling Andrés Hernández"
HIJO2_GRADO  = "Octavo"
HIJO2_ID     = "user240"

# ── Gmail ────────────────────────────────────
GMAIL_FROM   = "chdezhidalgo@gmail.com"
GMAIL_PASS   = os.environ["GMAIL_PASS"]
GMAIL_TO     = ["bromeror@gmail.com", "chernandezhidalgo@gmail.com"]

# ── Supabase ─────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

# ── Anthropic (opcional) ─────────────────────
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
USAR_COMPUTER_USE  = False
CLAUDE_MODEL       = "claude-opus-4-5"

# ── Vigencia ─────────────────────────────────
FECHA_FIN_VIGENCIA = "2026-11-20"

# ── Turnos ───────────────────────────────────
VENTANAS = {
    "manana":   {"desde_hora": 18, "delta_dias": -1, "label": "5:00 AM"},
    "mediodia": {"desde_hora":  5, "delta_dias":  0, "label": "1:00 PM"},
    "noche":    {"desde_hora": 13, "delta_dias":  0, "label": "6:00 PM"},
}

# ── Rutas locales ────────────────────────────
DIR_ADJUNTOS = "/tmp/adjuntos"
DIR_LOGS     = "/tmp/logs"
DIR_BASAL    = "/tmp/basal"
TESSERACT_CMD = "/usr/bin/tesseract"
