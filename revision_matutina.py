#!/usr/bin/env python3
"""
Script principal — Colegio: Revisión Programada Completa
Uso: python revision_matutina.py --turno [manana|mediodia|noche]
Programador de Tareas Windows: 3 entradas a las 5AM / 1PM / 6PM
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
from modules.mailer import enviar_correo, enviar_alerta_error
from modules.report import generar_reporte
from modules.wootit import revisar_estudiante, cargar_basal

TZ_CR = ZoneInfo('America/Costa_Rica')

# ── Logging ──────────────────────────────────────────────────────────────────
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


def main():
    # ── Argumento de turno ────────────────────────────────────────────────
    parser = argparse.ArgumentParser(description='Revisión Colegio')
    parser.add_argument('--turno', required=True,
                        choices=['manana', 'mediodia', 'noche'],
                        help='Turno de ejecución')
    args = parser.parse_args()
    turno = args.turno

    # ── Verificar vigencia ────────────────────────────────────────────────
    hoy = date.today()
    if hoy > date.fromisoformat(config.FECHA_FIN_VIGENCIA):
        logger.info("Tarea fuera del período de vigencia (después del 20/11/2026). Omitida.")
        sys.exit(0)
    hoy = date.today()
    if hoy > date.fromisoformat(config.FECHA_FIN_VIGENCIA):
        logger.info("Tarea fuera del período de vigencia (después del 20/11/2026). Omitida.")
        sys.exit(0)

    # ── Calcular ventana temporal
    cfg_turno = config.VENTANAS[turno]
    label_turno = cfg_turno['label']
    ahora = datetime.now(TZ_CR)
    desde = ahora.replace(
        hour=cfg_turno['desde_hora'], minute=0, second=0, microsecond=0
    ) + timedelta(days=cfg_turno['delta_dias'])
    logger.info(f"Turno: {label_turno} | Ventana: desde {desde} hasta {ahora}")

    # ── Iniciar navegador ─────────────────────────────────────────────────
    driver = get_driver(headless=False)
    adjuntos_para_correo = []

    try:
        # ── Login ─────────────────────────────────────────────────────────
        if not login(driver):
            logger.error("Login fallido tras 3 intentos.")
            enviar_alerta_error(label_turno, "Login falló 3 veces consecutivas.")
            sys.exit(1)

        datos_estudiantes = []

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
        datos_estudiantes.append(datos1)

        # Recopilar adjuntos de mensajes
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
            datos_estudiantes.append(datos2)
            for msg in datos2.get('mensajes', []):
                for adj in msg.get('adjuntos', []):
                    if adj.get('ruta'):
                        adjuntos_para_correo.append(adj['ruta'])

        # ── Generar reporte y enviar correo ───────────────────────────────
        cuerpo = generar_reporte(label_turno, datos_estudiantes)
        fecha_fmt = datetime.now(TZ_CR).strftime('%d/%m/%Y')
        asunto = f"Actualización Colegio - {label_turno} - {fecha_fmt}"
        enviar_correo(asunto, cuerpo, adjuntos_para_correo)
        logger.info("Revisión completada y correo enviado.")

    except Exception as e:
        logger.exception(f"Error inesperado en ejecución principal: {e}")
        enviar_alerta_error(label_turno, str(e))
    finally:
        driver.quit()


if __name__ == '__main__':
    main()
