"""
api_client.py v3.0.0 — Cliente HTTP WootIT con cookies + diagnóstico completo.

v3.0.0 cambios:
  - Diagnóstico HTML de calificaciones/asistencia/mensajes para ver estructura real
  - Cambio de estudiante mejorado: prueba múltiples endpoints CFC
  - Agrega userId a todos los requests que lo soporten
  - Log de WOOTITAPITOKEN para verificar qué estudiante tiene la sesión
"""
import base64
import json
import logging
import os
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

TZ_CR = ZoneInfo("America/Costa_Rica")
BASE  = config.BASE_URL

ESTUDIANTES_IDS = {
    "Carlos Emiliano": "user213",
    "Starling Andrés":  "user240",
}

ESTUDIANTES_NUM = {
    "Carlos Emiliano": 213,
    "Starling Andrés":  240,
}


def _parsear_cookie_string(cookie_str: str) -> dict:
    cookies = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            cookies[k.strip()] = v.strip()
    return cookies


def _decodificar_jwt(token: str) -> dict:
    """Decodifica payload de JWT sin verificar firma."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        # Agregar padding si falta
        payload += "=" * (4 - len(payload) % 4)
        return json.loads(base64.b64decode(payload).decode("utf-8"))
    except Exception:
        return {}


class WootITClient:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            "Accept":            "*/*",
            "Accept-Language":   "es-CR,es-ES;q=0.9,es;q=0.8",
            "Accept-Encoding":   "gzip, deflate, br, zstd",
            "X-Requested-With":  "XMLHttpRequest",
            "Origin":            "https://www.wootit.com",
            "Referer":           f"{BASE}/home/",
            "Sec-Fetch-Dest":    "empty",
            "Sec-Fetch-Mode":    "cors",
            "Sec-Fetch-Site":    "same-origin",
        })
        self._estudiante_activo = None
        self._user_id_activo = None
        self._cookies_dict = {}

    def login(self) -> bool:
        cookie_str = os.environ.get("WOOTIT_COOKIES", "").strip()
        if not cookie_str:
            logger.error("❌ Secret WOOTIT_COOKIES no configurado.")
            return False

        self._cookies_dict = _parsear_cookie_string(cookie_str)
        for name, value in self._cookies_dict.items():
            self.session.cookies.set(name, value, domain="www.wootit.com")

        logger.info(f"🍪 Cookies cargadas: {list(self._cookies_dict.keys())}")

        # Decodificar JWT para ver qué usuario/estudiante tiene la sesión
        jwt = self._cookies_dict.get("WOOTITAPITOKEN", "")
        if jwt:
            payload = _decodificar_jwt(jwt)
            logger.info(f"🔑 JWT payload: {payload}")

        # QUSUARIO = ID del padre/tutor en sesión
        qusuario = self._cookies_dict.get("QUSUARIO", "")
        logger.info(f"👤 QUSUARIO (tutor): {qusuario}")

        try:
            r = self.cfc_get("home/cfc/home.cfc", "getNext")
            if r:
                logger.info("✅ Sesión WootIT válida")
                # Log estructura completa de getNext para diagnóstico
                for k, v in r.items():
                    if isinstance(v, dict) and "COLUMNS" in v:
                        rows = v.get("DATA", [])
                        logger.info(f"   getNext.{k}: cols={v['COLUMNS']}, rows={len(rows)}")
                        if rows:
                            logger.info(f"   Primera fila: {dict(zip(v['COLUMNS'], rows[0]))}")
                return True
            else:
                logger.warning("⚠️  getNext devolvió vacío")
                return True
        except Exception as e:
            logger.error(f"Error verificando sesión: {e}")
            return False

    def cambiar_estudiante(self, nombre: str) -> bool:
        """
        Establece el userId del estudiante activo.
        WootIT usa userId como parámetro en los CFCs — no hay endpoint
        de "cambio de sesión" server-side. El userId se pasa directamente
        en cada llamada CFC como parámetro.
        """
        user_num = ESTUDIANTES_NUM.get(nombre)
        if not user_num:
            logger.error(f"ID no encontrado para: {nombre}")
            return False

        self._user_id_activo = user_num
        self._estudiante_activo = nombre
        logger.info(f"✅ Estudiante activo: {nombre} (userId={user_num})")
        return True

    def cfc_get(self, cfc_path: str, method: str, params: dict = None) -> dict:
        url = f"{BASE}/{cfc_path}"
        p = {"method": method, "returnformat": "json"}
        if self._user_id_activo:
            p["idUsuario"] = self._user_id_activo
            p["userId"]    = self._user_id_activo
        if params:
            p.update(params)
        resp = self.session.get(url, params=p, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def cfc_post(self, cfc_path: str, method: str, data: dict = None) -> dict:
        url = f"{BASE}/{cfc_path}"
        d = {"method": method, "returnformat": "json"}
        if self._user_id_activo:
            d["idUsuario"] = self._user_id_activo
            d["userId"]    = self._user_id_activo
        if data:
            d.update(data)
        resp = self.session.post(url, data=d, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def html_get(self, path: str, params: dict = None) -> BeautifulSoup:
        url = f"{BASE}/{path}"
        p = params or {}
        if self._user_id_activo:
            p = {**p, "idUsuario": self._user_id_activo}
        resp = self.session.get(url, params=p if p else None, timeout=20)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    @staticmethod
    def query_to_dicts(data, key: str = None) -> list:
        if key:
            data = data.get(key, {}) if isinstance(data, dict) else {}
        if not isinstance(data, dict):
            return []
        columns = [c.upper() for c in data.get("COLUMNS", [])]
        return [dict(zip(columns, row)) for row in data.get("DATA", [])]

    # ── Endpoints ─────────────────────────────────────────────────────────────

    def get_proximos_eventos(self) -> dict:
        try:
            return self.cfc_get("home/cfc/home.cfc", "getNext")
        except Exception as e:
            logger.warning(f"get_proximos_eventos: {e}")
            return {}

    def get_posts_aula_virtual(self, filtro: str = "todos") -> dict:
        try:
            return self.cfc_get(
                "aulavirtual/cfc/aulavirtual.cfc", "getPostsPorUsuario",
                {"filter": filtro, "userRole": "padres", "fecha": ""},
            )
        except Exception as e:
            logger.warning(f"get_posts_aula_virtual({filtro}): {e}")
            return {}

    def get_post_detalle(self, id_post: int) -> dict:
        try:
            return self.cfc_get(
                "aulavirtual/cfc/aulavirtual.cfc", "getPost", {"id": id_post}
            )
        except Exception as e:
            logger.warning(f"get_post_detalle({id_post}): {e}")
            return {}

    def get_calificaciones_html(self) -> BeautifulSoup:
        try:
            return self.html_get("calificaciones/estudiante.cfm")
        except Exception as e:
            logger.warning(f"get_calificaciones_html: {e}")
            return BeautifulSoup("", "lxml")

    def get_mensajes_html(self) -> BeautifulSoup:
        try:
            return self.html_get("comunicacion/mensajes/recibidos.cfm")
        except Exception as e:
            logger.warning(f"get_mensajes_html: {e}")
            return BeautifulSoup("", "lxml")

    def get_asistencia_html(self) -> BeautifulSoup:
        try:
            return self.html_get(
                "asistenciayconductaEst/index.cfm", {"sec": "asistencia"}
            )
        except Exception as e:
            logger.warning(f"get_asistencia_html: {e}")
            return BeautifulSoup("", "lxml")

    def get_boleta_html(self) -> BeautifulSoup:
        try:
            return self.html_get(
                "asistenciayconductaEst/index.cfm", {"sec": "boletas"}
            )
        except Exception as e:
            logger.warning(f"get_boleta_html: {e}")
            return BeautifulSoup("", "lxml")

    def get_anotaciones_html(self) -> BeautifulSoup:
        try:
            return self.html_get(
                "asistenciayconductaEst/index.cfm", {"sec": "anotaciones"}
            )
        except Exception as e:
            logger.warning(f"get_anotaciones_html: {e}")
            return BeautifulSoup("", "lxml")
