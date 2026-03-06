"""
Módulo de envío de correo vía Gmail SMTP con adjuntos.
"""

import logging
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def enviar_correo(asunto: str, cuerpo: str, adjuntos_rutas: list = None) -> bool:
    try:
        msg = MIMEMultipart()
        msg['From']    = config.GMAIL_FROM
        msg['To']      = ', '.join(config.GMAIL_TO)
        msg['Subject'] = asunto
        msg.attach(MIMEText(cuerpo, 'plain', 'utf-8'))

        for ruta in (adjuntos_rutas or []):
            if ruta and Path(ruta).exists():
                with open(ruta, 'rb') as f:
                    parte = MIMEBase('application', 'octet-stream')
                    parte.set_payload(f.read())
                encoders.encode_base64(parte)
                parte.add_header('Content-Disposition',
                                 f'attachment; filename="{Path(ruta).name}"')
                msg.attach(parte)

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as servidor:
            servidor.login(config.GMAIL_FROM, config.GMAIL_PASS)
            servidor.sendmail(config.GMAIL_FROM, config.GMAIL_TO, msg.as_bytes())

        logger.info(f"Correo enviado: {asunto}")
        return True
    except Exception as e:
        logger.error(f"Error enviando correo: {e}")
        return False


def enviar_alerta_error(turno_label: str, detalle: str):
    asunto = f"⚠️ ERROR LOGIN - Revisión {turno_label}"
    cuerpo = (f"No se pudo completar la revisión programada de las {turno_label}.\n\n"
              f"Detalle del error:\n{detalle}\n\nRevise el log para más información.")
    enviar_correo(asunto, cuerpo)
