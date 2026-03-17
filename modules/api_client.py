"""
api_client.py v2.0.0 — Cliente HTTP WootIT con cookies de sesión inyectadas.

DIAGNÓSTICO DEFINITIVO:
  WootIT bloquea el POST de login desde IPs de datacenter (Azure/GitHub Actions).
  El servidor devuelve HTTP 200 pero no redirige a /home/ — rechaza credenciales
  cuando detecta que la IP no es residencial.

SOLUCIÓN:
  Inyectar las cookies de una sesión real (obtenidas del navegador del usuario)
  como GitHub Secret WOOTIT_COOKIES. El cliente las carga directamente sin
  necesidad de hacer login.

  Las cookies críticas de WootIT son de larga duración (expiran 2026-2027),
  por lo que esta solución es estable. Cuando expiren, se renuevan copiando
  las cookies del navegador nuevamente.

FORMATO DEL SECRET WOOTIT_COOKIES:
  String en formato HTTP Cookie header, separado por "; "
  Ejemplo:
  cfid=abc123; cftoken=0; QUSUARIO=480; WOOTAUTOLOG=1; WOOTA=xxx; ...

ARQUITECTURA:
  Stack: Lucee 6.2.3.35 (ColdFusion OSS) sobre Undertow/Java
  Auth: Cookie de sesión — cfid + cftoken + WOOTA/WOOTP/WOOTU + WOOTITAPITOKEN
  API JSON: ColdFusion Components (.cfc?method=X&returnformat=json)
  Formato: Lucee QueryBean {COLUMNS:[...], DATA:[[...],...]}
"""
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
    """
    Convierte un string de cookies HTTP en dict.
    Formato entrada: "cfid=abc; cftoken=0; WOOTA=xxx"
    """
    cookies = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            cookies[k.strip()] = v.strip()
    return cookies


class WootITClient:
    """
    Cliente de sesión HTTP para WootIT.
    Carga cookies desde el secret WOOTIT_COOKIES en lugar de hacer login.
    """

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
            "Content-Type":      "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With":  "XMLHttpRequest",
            "Origin":            "https://www.wootit.com",
            "Referer":           f"{BASE}/home/",
            "Sec-Fetch-Dest":    "empty",
            "Sec-Fetch-Mode":    "cors",
            "Sec-Fetch-Site":    "same-origin",
        })
        self._estudiante_activo = None

    # ── Autenticación via cookies ─────────────────────────────────────────────

    def login(self) -> bool:
        """
        Carga cookies de sesión desde el secret WOOTIT_COOKIES.
        No hace POST de credenciales — inyecta la sesión directamente.
        """
        cookie_str = os.environ.get("WOOTIT_COOKIES", "").strip()

        if not cookie_str:
            logger.error(
                "❌ Secret WOOTIT_COOKIES no configurado. "
                "Exporta las cookies de tu navegador y agrégalas como secret."
            )
            return False

        # Cargar cookies en la sesión
        cookies_dict = _parsear_cookie_string(cookie_str)
        for name, value in cookies_dict.items():
            self.session.cookies.set(name, value, domain="www.wootit.com")

        logger.info(f"🍪 Cookies cargadas: {list(cookies_dict.keys())}")

        # Verificar que la sesión es válida llamando al home
        try:
            resp = self.session.get(f"{BASE}/home/", timeout=20, allow_redirects=True)
            if "/login" in resp.url:
                logger.error(
                    f"❌ Sesión inválida — redirigido a login. "
                    "Las cookies pueden haber expirado. Actualiza WOOTIT_COOKIES."
                )
                return False

            # Verificar con CFC que retorna datos reales
            r = self.cfc_get("home/cfc/home.cfc", "getNext")
            if r:
                logger.info("✅ Sesión WootIT válida — datos del home obtenidos")
                return True
            else:
                logger.warning("⚠️  home.cfc/getNext devolvió vacío — sesión puede ser parcial")
                return True  # Continuar de todas formas

        except Exception as e:
            logger.error(f"Error verificando sesión: {e}")
            return False

    # ── Cambio de estudiante ──────────────────────────────────────────────────

    def cambiar_estudiante(self, nombre: str) -> bool:
        """
        Cambia el perfil activo al estudiante indicado.
        WootIT usa el endpoint home.cfc con el ID del estudiante.
        """
        user_num = ESTUDIANTES_NUM.get(nombre)
        if not user_num:
            logger.error(f"ID numérico no encontrado para: {nombre}")
            return False

        try:
            # Intentar cambio via CFC
            r = self.cfc_get("home/cfc/home.cfc", "cambiarEstudiante",
                             {"idUsuario": user_num})
            logger.info(f"cambiarEstudiante({nombre}): {r}")
        except Exception:
            pass

        # Intentar via GET al home con parámetro
        try:
            resp = self.session.get(
                f"{BASE}/home/",
                params={"idUsuario": user_num},
                timeout=15,
            )
            logger.info(f"GET home/?idUsuario={user_num}: {resp.status_code}")
        except Exception as e:
            logger.warning(f"cambiar_estudiante GET: {e}")

        self._estudiante_activo = nombre
        logger.info(f"Estudiante activo establecido: {nombre}")
        return True

    # ── Llamadas base ─────────────────────────────────────────────────────────

    def cfc_get(self, cfc_path: str, method: str, params: dict = None) -> dict:
        """Llama un endpoint CFC GET y retorna JSON."""
        url = f"{BASE}/{cfc_path}"
        p = {"method": method, "returnformat": "json"}
        if params:
            p.update(params)
        resp = self.session.get(url, params=p, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def cfc_post(self, cfc_path: str, method: str, data: dict = None) -> dict:
        """Llama un endpoint CFC POST y retorna JSON."""
        url = f"{BASE}/{cfc_path}"
        d = {"method": method, "returnformat": "json"}
        if data:
            d.update(data)
        resp = self.session.post(url, data=d, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def html_get(self, path: str, params: dict = None) -> BeautifulSoup:
        """GET de página HTML, retorna BeautifulSoup."""
        url = f"{BASE}/{path}"
        resp = self.session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    # ── Formato Lucee QueryBean ───────────────────────────────────────────────

    @staticmethod
    def query_to_dicts(data, key: str = None) -> list:
        """Convierte Lucee QueryBean a lista de dicts."""
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
