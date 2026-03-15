#!/usr/bin/env python3
"""
Script principal — ColegioCR: Revisión Programada Completa
Uso: python revision_matutina.py --turno [manana|mediodia|noche]
GitHub Actions: 3 ejecuciones diarias a las 5AM / 1PM / 6PM (hora CR)
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from modules.browser import get_driver, login, cambiar_estudiante
from modules.clasificador import clasificar_mensaje                          # BUG [21] CORREGIDO: ahora se importa y usa
from modules.database import registrar_ejecucion, guardar_mensaje, guardar_calificacion  # BUG [20] CORREGIDO
from modules.mailer import enviar_correo, enviar_alerta_error
from modules.report import generar_reporte
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


def _enriquecer_mensajes(mensajes: list) -> list:
    """
    BUG [21] CORREGIDO: Aplica clasificador a cada mensaje para asignar
    categoría, urgencia normalizada y si requiere acción del padre.
    """
    for msg in mensajes:
        if 'error' in msg or 'analisis_visual' in msg:
            continue
        clasificacion = clasificar_mensaje(
            msg.get('asunto', ''),
            msg.get('cuerpo', '')
        )
        msg['categoria']       = clasificacion['categoria']
        msg['requiere_accion'] = clasificacion['requiere_accion']
        msg['fecha_limite']    = clasificacion['fecha_limite']
        msg['monto']           = clasificacion['monto']
        # Normalizar urgencia a Alta/Media/Baja si clasificador la sobreescribe
        if clasificacion['urgencia'] == 'alta':
            msg['urgencia'] = 'Alta'
        elif clasificacion['urgencia'] == 'media' and msg.get('urgencia') == 'Baja':
            msg['urgencia'] = 'Media'
    return mensajes


def _persistir_en_supabase(datos_estudiantes: list, turno: str, correo_ok: bool):
    """
    BUG [20] CORREGIDO: Persiste en Supabase mensajes, calificaciones
    y registra la ejecución. Fallo de BD no interrumpe el proceso.
    """
    try:
        for est in datos_estudiantes:
            nombre = est.get('estudiante', '')
            for msg in est.get('mensajes', []):
                if 'error' not in msg and 'analisis_visual' not in msg:
                    guardar_mensaje(nombre, msg, turno)
            for cal in est.get('calificaciones', []):
                if 'error' not in cal and 'analisis_visual' not in cal:
                    guardar_calificacion(nombre, cal)
        registrar_ejecucion(
            turno=turno,
            estado='exitoso' if correo_ok else 'error_correo',
            detalle='',
            correo_enviado=correo_ok
        )
        logger.info("Datos persistidos en Supabase.")
    except Exception as e:
        logger.warning(f"No se pudo persistir en Supabase (no crítico): {e}")


def main():
    # ── Argumento de turno ────────────────────────────────────────────────
    parser = argparse.ArgumentParser(description='Revisión ColegioCR')
    parser.add_argument('--turno', required=True,
                        choices=['manana', 'mediodia', 'noche'],
                        help='Turno de ejecución')
    args = parser.parse_args()
    turno = args.turno

    # ── Verificar vigencia ────────────────────────────────────────────────
    hoy = date.today()
    if hoy > date.fromisoformat(config.FECHA_FIN_VIGENCIA):
        logger.info("Tarea fuera del período de vigencia. Omitida.")
        sys.exit(0)

    # ── Calcular ventana temporal ─────────────────────────────────────────
    cfg_turno = config.VENTANAS[turno]
    label_turno = cfg_turno['label']
    ahora = datetime.now(TZ_CR)
    desde = ahora.replace(
        hour=cfg_turno['desde_hora'], minute=0, second=0, microsecond=0
    ) + timedelta(days=cfg_turno['delta_dias'])
    logger.info(f"Turno: {label_turno} | Ventana: desde {desde} hasta {ahora}")

    # ── Iniciar navegador ─────────────────────────────────────────────────
    # BUG [14] CORREGIDO: headless automático en CI (GitHub Actions), False en local
    en_ci = os.environ.get("CI", "").lower() == "true"
    driver = get_driver(headless=en_ci)
    adjuntos_para_correo = []
    datos_estudiantes = []
    correo_ok = False

    try:
        # ── Login ─────────────────────────────────────────────────────────
        if not login(driver):
            logger.error("Login fallido tras 3 intentos.")
            registrar_ejecucion(turno, 'error_login', 'Login falló 3 veces consecutivas.', False)
            enviar_alerta_error(label_turno, "Login falló 3 veces consecutivas.")
            sys.exit(1)

        # ── Estudiante 1: Carlos Emiliano (7° Grado) ──────────────────────
        basal1 = cargar_basal('emiliano')
        datos1 = revisar_estudiante(
            driver,
            label=config.HIJO1_LABEL,
            grado=config.HIJO1_GRADO,
            nombre_corto=config.HIJO1_NOMBRE,
            ventana_desde=desde,
            basal=basal1
        )
        datos1['mensajes'] = _enriquecer_mensajes(datos1.get('mensajes', []))  # BUG [21]
        datos_estudiantes.append(datos1)

        for msg in datos1.get('mensajes', []):
            for adj in msg.get('adjuntos', []):
                if adj.get('ruta'):
                    adjuntos_para_correo.append(adj['ruta'])

        # ── Cambiar a Estudiante 2: Starling Andrés (8° Grado) ────────────
        cambio_ok = cambiar_estudiante(driver, 'Starling Andrés', '8° Grado')
        if not cambio_ok:
            logger.error("No se pudo cambiar a Starling Andrés.")
            datos_estudiantes.append({
                'estudiante': config.HIJO2_LABEL,
                'nombre_corto': config.HIJO2_NOMBRE,
                'grado': config.HIJO2_GRADO,
                'mensajes': [{'error': 'No procesado — error en cambio de perfil'}],
                'calificaciones': [], 'asistencia': [], 'boleta': [],
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
            datos2['mensajes'] = _enriquecer_mensajes(datos2.get('mensajes', []))  # BUG [21]
            datos_estudiantes.append(datos2)
            for msg in datos2.get('mensajes', []):
                for adj in msg.get('adjuntos', []):
                    if adj.get('ruta'):
                        adjuntos_para_correo.append(adj['ruta'])

        # ── Generar reporte y enviar correo ───────────────────────────────
        cuerpo = generar_reporte(label_turno, datos_estudiantes)
        fecha_fmt = datetime.now(TZ_CR).strftime('%d/%m/%Y')
        asunto = f"Actualización Colegio - {label_turno} - {fecha_fmt}"
        correo_ok = enviar_correo(asunto, cuerpo, adjuntos_para_correo)
        logger.info("Revisión completada y correo enviado.")

    except Exception as e:
        logger.exception(f"Error inesperado en ejecución principal: {e}")
        try:
            registrar_ejecucion(turno, 'error_critico', str(e), False)
        except Exception:
            pass
        enviar_alerta_error(label_turno, str(e))
    finally:
        # BUG [20] CORREGIDO: persistir siempre, incluso si hubo errores parciales
        if datos_estudiantes:
            _persistir_en_supabase(datos_estudiantes, turno, correo_ok)
        driver.quit()


if __name__ == '__main__':
    main()
