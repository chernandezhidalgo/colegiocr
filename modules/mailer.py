"""
mailer.py — Envío de correo vía Gmail SMTP.
v3.0.0: soporte HTML + texto plano (multipart/alternative).
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


def enviar_correo(asunto, cuerpo_html, adjuntos_rutas=None):
    """
    Envía correo HTML con fallback a texto plano.
    Retorna True si el envío fue exitoso.
    """
    try:
        msg = MIMEMultipart('alternative')
        msg['From']    = config.GMAIL_FROM
        msg['To']      = ', '.join(config.GMAIL_TO)
        msg['Subject'] = asunto

        # Versión texto plano como fallback (clientes que no soportan HTML)
        texto_plano = "Este correo requiere un cliente de correo con soporte HTML."
        msg.attach(MIMEText(texto_plano, 'plain', 'utf-8'))
        msg.attach(MIMEText(cuerpo_html, 'html', 'utf-8'))

        # Adjuntos
        for ruta in (adjuntos_rutas or []):
            if ruta and Path(ruta).exists():
                with open(ruta, 'rb') as f:
                    parte = MIMEBase('application', 'octet-stream')
                    parte.set_payload(f.read())
                encoders.encode_base64(parte)
                parte.add_header('Content-Disposition',
                                 f'attachment; filename="{Path(ruta).name}"')
                msg.attach(parte)

        with smtplib.SMTP('smtp.gmail.com', 587) as servidor:
            servidor.ehlo()
            servidor.starttls()
            servidor.ehlo()
            servidor.login(config.GMAIL_FROM, config.GMAIL_PASS)
            servidor.sendmail(config.GMAIL_FROM, config.GMAIL_TO, msg.as_bytes())

        logger.info(f"Correo enviado: {asunto}")
        return True
    except Exception as e:
        logger.error(f"Error enviando correo: {e}")
        return False


def enviar_alerta_error(turno_label, detalle):
    asunto = f"ColegioCR ERROR — {turno_label}"
    cuerpo = f"""<html><body>
    <h2 style="color:#D32F2F">Error en revisión ColegioCR</h2>
    <p><strong>Turno:</strong> {turno_label}</p>
    <p><strong>Detalle:</strong></p>
    <pre style="background:#F5F5F5;padding:12px;border-radius:4px">{detalle}</pre>
    <p>Revisar los logs en GitHub Actions para más información.</p>
    </body></html>"""
    enviar_correo(asunto, cuerpo)
