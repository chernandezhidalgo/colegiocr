"""
Módulo de base de datos: integración con Supabase.
Guarda historial de mensajes, calificaciones, asistencia,
anotaciones, tareas y registro de ejecuciones.
BUG [19] CORREGIDO: float(nota) protegido con try/except.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from supabase import create_client, Client
import config

logger = logging.getLogger(__name__)
TZ_CR = ZoneInfo("America/Costa_Rica")

_client: Client = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


def guardar_mensaje(estudiante: str, msg: dict, turno: str):
    try:
        get_client().table("mensajes").insert({
            "estudiante":        estudiante,
            "asunto":            msg.get("asunto"),
            "remitente":         msg.get("remitente"),
            "fecha_mensaje":     msg.get("fecha"),
            "cuerpo":            msg.get("cuerpo"),
            "resumen":           msg.get("resumen"),
            "categoria":         msg.get("categoria"),
            "urgencia":          msg.get("urgencia"),
            "requiere_accion":   msg.get("requiere_accion", False),
            "ya_leido":          msg.get("ya_leido", False),
            "tiene_adjunto":     bool(msg.get("adjuntos")),
            "adjunto_nombre":    msg.get("adjunto_nombre"),
            "adjunto_contenido": msg.get("adjunto_contenido"),
            "turno":             turno,
        }).execute()
    except Exception as e:
        logger.error(f"DB error guardando mensaje: {e}")


def guardar_calificacion(estudiante: str, cal: dict):
    try:
        nota     = cal.get("nota_nueva") or cal.get("nota")
        nota_ant = cal.get("nota_anterior")

        # BUG [19] CORREGIDO: conversión segura a float
        variacion = None
        try:
            if nota and nota_ant and nota_ant != '(sin basal)':
                variacion = round(float(nota) - float(nota_ant), 2)
        except (ValueError, TypeError):
            variacion = None

        get_client().table("calificaciones").insert({
            "estudiante":     estudiante,
            "materia":        cal.get("materia"),
            "nota":           nota,
            "nota_anterior":  nota_ant,
            "variacion":      variacion,
            "fecha_registro": cal.get("fecha"),
        }).execute()
    except Exception as e:
        logger.error(f"DB error guardando calificación: {e}")


def guardar_asistencia(estudiante: str, reg: dict):
    try:
        get_client().table("asistencia").insert({
            "estudiante": estudiante,
            "fecha":      reg.get("fecha"),
            "tipo":       reg.get("tipo"),
            "materia":    reg.get("materia"),
            "periodo":    reg.get("periodo"),
        }).execute()
    except Exception as e:
        logger.error(f"DB error guardando asistencia: {e}")


def guardar_anotacion(estudiante: str, anot: dict):
    try:
        get_client().table("anotaciones").insert({
            "estudiante":  estudiante,
            "fecha":       anot.get("fecha"),
            "tipo":        anot.get("tipo"),
            "descripcion": anot.get("descripcion"),
            "profesor":    anot.get("profesor"),
        }).execute()
    except Exception as e:
        logger.error(f"DB error guardando anotación: {e}")


def guardar_tarea(estudiante: str, tarea: dict):
    try:
        get_client().table("tareas").insert({
            "estudiante":      estudiante,
            "materia":         tarea.get("materia"),
            "nombre":          tarea.get("nombre"),
            "fecha_limite":    tarea.get("fecha_limite"),
            "descripcion":     tarea.get("descripcion"),
            "adjunto_resumen": tarea.get("adjunto_resumen"),
        }).execute()
    except Exception as e:
        logger.error(f"DB error guardando tarea: {e}")


def registrar_ejecucion(turno: str, estado: str, detalle: str = "", correo_enviado: bool = False):
    try:
        get_client().table("ejecuciones").insert({
            "turno":          turno,
            "estado":         estado,
            "detalle":        detalle,
            "correo_enviado": correo_enviado,
        }).execute()
    except Exception as e:
        logger.error(f"DB error registrando ejecución: {e}")
