#!/usr/bin/env python3
"""
revision_matutina.py — ColegioCR v3.0.0
Ejecución única diaria a las 6:00 PM (hora CR).
"""
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from modules.browser import get_driver, login, cambiar_estudiante
from modules.clasificador import clasificar_mensaje
from modules.database import registrar_ejecucion, guardar_mensaje, guardar_calificacion
from modules.mailer import enviar_correo, enviar_alerta_error
from modules.report import generar_reporte, construir_asunto
from modules.wootit import revisar_estudiante, cargar_basal

TZ_CR = ZoneInfo('America/Costa_Rica')

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs(config.DIR_LOGS, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(
            Path(config.DIR_LOGS) / f"revision_{date.today()}.log",
            encoding='utf-8'
        ),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def _enriquecer_mensajes(mensajes):
    """Aplica clasificador a cada mensaje para asignar categoría y urgencia normalizada."""
    for msg in mensajes:
        if 'error' in msg or 'analisis_visual' in msg:
            continue
        try:
            clasificacion = clasificar_mensaje(
                msg.get('asunto', ''),
                msg.get('cuerpo', '')
            )
            msg['categoria']       = clasificacion['categoria']
            msg['requiere_accion'] = clasificacion['requiere_accion']
            msg['fecha_limite']    = clasificacion['fecha_limite']
            msg['monto']           = clasificacion['monto']
            if clasificacion['urgencia'] == 'alta':
                msg['urgencia'] = 'Alta'
            elif clasificacion['urgencia'] == 'media' and msg.get('urgencia') == 'Baja':
                msg['urgencia'] = 'Media'
        except Exception as e:
            logger.warning(f'Error clasificando mensaje: {e}')
    return mensajes


def _persistir_en_supabase(datos_estudiantes, turno, correo_ok):
    """Persiste datos en Supabase. Fallo de BD no interrumpe el proceso."""
    try:
        for est in datos_estudiantes:
            nombre = est.get('estudiante', '')
            for msg in est.get('mensajes', []):
                if 'error' not in msg and 'analisis_visual' not in msg:
                    guardar_mensaje(nombre, msg, turno)
            for cal in est.get('calificaciones', []):
                if isinstance(cal, dict) and 'error' not in cal and 'analisis_visual' not in cal:
                    guardar_calificacion(nombre, cal)
        registrar_ejecucion(
            turno=turno,
            estado='exitoso' if correo_ok else 'error_correo',
            detalle='',
            correo_enviado=correo_ok
        )
        logger.info("Datos persistidos en Supabase.")
    except Exception as e:
        logger.warning(f"No se pudo persistir en Supabase (no critico): {e}")


def main():
    # ── Verificar vigencia ────────────────────────────────────────────────
    hoy = date.today()
    if hoy > date.fromisoformat(config.FECHA_FIN_VIGENCIA):
        logger.info("Tarea fuera del periodo de vigencia. Omitida.")
        sys.exit(0)

    # ── Ventana temporal: todo el día de hoy ──────────────────────────────
    # Ejecución única diaria: captura todo lo ocurrido desde las 00:00 de hoy
    ahora = datetime.now(TZ_CR)
    desde = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    logger.info(f"Revision diaria | Ventana: {desde.date()} 00:00 hasta {ahora.strftime('%H:%M')}")

    # ── Iniciar navegador ─────────────────────────────────────────────────
    en_ci  = os.environ.get("CI", "").lower() == "true"
    driver = get_driver(headless=en_ci)
    adjuntos_para_correo = []
    datos_estudiantes    = []
    correo_ok            = False

    try:
        # ── Login ─────────────────────────────────────────────────────────
        if not login(driver):
            logger.error("Login fallido tras 3 intentos.")
            registrar_ejecucion('noche', 'error_login', 'Login fallo 3 veces.', False)
            enviar_alerta_error('6:00 PM', "Login fallo 3 veces consecutivas.")
            sys.exit(1)

        # ── Estudiante 1: Carlos Emiliano ─────────────────────────────────
        basal1 = cargar_basal('emiliano')
        datos1 = revisar_estudiante(
            driver,
            label=config.HIJO1_LABEL,
            grado=config.HIJO1_GRADO,
            nombre_corto=config.HIJO1_NOMBRE,
            ventana_desde=desde,
            basal=basal1
        )
        datos1['mensajes'] = _enriquecer_mensajes(datos1.get('mensajes', []))
        datos_estudiantes.append(datos1)

        for msg in datos1.get('mensajes', []):
            for adj in msg.get('adjuntos', []):
                if adj.get('ruta'):
                    adjuntos_para_correo.append(adj['ruta'])

        # ── Cambiar a Estudiante 2: Starling Andrés ───────────────────────
        cambio_ok = cambiar_estudiante(driver, 'Starling Andrés', '8° Grado')
        if not cambio_ok:
            logger.error("No se pudo cambiar a Starling Andres.")
            datos_estudiantes.append({
                'estudiante': config.HIJO2_LABEL,
                'nombre_corto': config.HIJO2_NOMBRE,
                'grado': config.HIJO2_GRADO,
                'mensajes': [{'error': 'No procesado — error en cambio de perfil'}],
                'calificaciones': [], 'asistencia': {}, 'boleta': [],
                'anotaciones': [], 'aula_virtual': {}, 'agenda': [],
            })
        else:
            basal2 = cargar_basal('andres')
            datos2 = revisar_estudiante(
                driver,
                label=config.HIJO2_LABEL,
                grado=config.HIJO2_GRADO,
                nombre_corto=config.HIJO2_NOMBRE,
                ventana_desde=desde,
                basal=basal2
            )
            datos2['mensajes'] = _enriquecer_mensajes(datos2.get('mensajes', []))
            datos_estudiantes.append(datos2)
            for msg in datos2.get('mensajes', []):
                for adj in msg.get('adjuntos', []):
                    if adj.get('ruta'):
                        adjuntos_para_correo.append(adj['ruta'])

        # ── Generar reporte HTML y enviar ─────────────────────────────────
        cuerpo_html = generar_reporte('6:00 PM', datos_estudiantes)
        asunto      = construir_asunto(datos_estudiantes)
        correo_ok   = enviar_correo(asunto, cuerpo_html, adjuntos_para_correo)

        if correo_ok:
            logger.info(f"Correo enviado: {asunto}")
        else:
            logger.error("Fallo al enviar correo.")

    except Exception as e:
        logger.exception(f"Error inesperado: {e}")
        try:
            registrar_ejecucion('noche', 'error_critico', str(e), False)
        except Exception:
            pass
        enviar_alerta_error('6:00 PM', str(e))
    finally:
        if datos_estudiantes:
            _persistir_en_supabase(datos_estudiantes, 'noche', correo_ok)
        driver.quit()


if __name__ == '__main__':
    main()
