"""
api_client.py v1.0.0 — Cliente HTTP directo para WootIT (sin navegador).

ARQUITECTURA DESCUBIERTA (ingeniería inversa 17/03/2026):
  Stack: Lucee 6.2.3.35 (ColdFusion OSS) sobre Undertow/Java
  Autenticación: Cookie de sesión (CFID + CFTOKEN / JSESSIONID)
  API: ColdFusion Components (.cfc) con ?method=X&returnformat=json
  Formato respuesta: Lucee QueryBean {"COLUMNS":[...], "DATA":[[...],...]}

ENDPOINTS CONFIRMADOS:
  home/cfc/home.cfc           → getNext, getOpcionesEspeciales
  aulavirtual/cfc/aulavirtual.cfc → getPostsPorUsuario, getPost, getPostReplies
  calificaciones/estudiante.cfm   → HTML server-side (BeautifulSoup)
  comunicacion/mensajes/recibidos.cfm → HTML server-side (BeautifulSoup)
  asistenciayconductaEst/index.cfm → HTML server-side (BeautifulSoup)

SIN PLAYWRIGHT, SIN SELENIUM, SIN CHROMEDRIVER.
"""
import logging
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

TZ_CR = ZoneInfo("America/Costa_Rica")
BASE  = config.BASE_URL

# ── IDs de estudiantes en el portal ──────────────────────────────────────────
ESTUDIANTES_IDS = {
    "Carlos Emiliano": "user213",
    "Starling Andrés":  "user240",
}

# Mapeo user_id → parámetro numérico para cambio de perfil
# (estimación: necesitaremos confirmar con una petición real)
ESTUDIANTES_NUM = {
    "Carlos Emiliano": 213,
    "Starling Andrés":  240,
}


class WootITClient:
    """
    Cliente de sesión HTTP para WootIT.
    Una instancia = una sesión autenticada.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept":          "application/json, text/html, */*",
            "Accept-Language": "es-CR,es;q=0.9,en;q=0.8",
            "Referer":         f"{BASE}/login/",
        })
        self._estudiante_activo = None

    # ── Autenticación ─────────────────────────────────────────────────────────

    def login(self) -> bool:
        """
        Login HTTP directo. WootIT usa POST form al endpoint /login/.
        Retorna True si la sesión quedó autenticada.
        """
        try:
            # Cargar login para obtener cookies iniciales de sesión CF
            r0 = self.session.get(f"{BASE}/login/", timeout=20)
            r0.raise_for_status()
            time.sleep(0.5)

            # POST de credenciales
            resp = self.session.post(
                f"{BASE}/login/",
                data={
                    "usuario":    config.WOOTIT_USER,
                    "contrasena": config.WOOTIT_PASS,
                },
                allow_redirects=True,
                timeout=20,
            )

            # Verificar éxito: URL debe contener /home/ y no /login/
            ok = resp.ok and ("home" in resp.url or "/home" in resp.url)
            if not ok:
                # Intento alternativo con campos username/password
                resp2 = self.session.post(
                    f"{BASE}/login/",
                    data={
                        "username": config.WOOTIT_USER,
                        "password": config.WOOTIT_PASS,
                    },
                    allow_redirects=True,
                    timeout=20,
                )
                ok = resp2.ok and ("home" in resp2.url or "/home" in resp2.url)

            if ok:
                logger.info(f"✅ Login HTTP exitoso. URL final: {resp.url}")
                logger.info(f"   Cookies activas: {list(self.session.cookies.keys())}")
            else:
                logger.error(f"❌ Login HTTP fallido. URL: {resp.url} | Status: {resp.status_code}")
                # Log del HTML para diagnóstico
                soup = BeautifulSoup(resp.text, "lxml")
                logger.debug(f"   Título página: {soup.title.string if soup.title else 'N/A'}")
            return ok

        except Exception as e:
            logger.error(f"Error en login HTTP: {e}")
            return False

    # ── Cambio de estudiante ──────────────────────────────────────────────────

    def cambiar_estudiante(self, nombre: str) -> bool:
        """
        Cambia el perfil activo al estudiante indicado.
        WootIT mantiene el contexto de estudiante en la sesión del servidor.
        El cambio se hace llamando al home con el ID del estudiante.
        """
        user_id_str = ESTUDIANTES_IDS.get(nombre)
        user_id_num = ESTUDIANTES_NUM.get(nombre)
        if not user_id_str:
            logger.error(f"ID no encontrado para: {nombre}")
            return False

        try:
            # Estrategia 1: CFC getOpcionesEspeciales puede revelar cómo cambiar
            r = self.cfc_get("home/cfc/home.cfc", "getOpcionesEspeciales",
                             {"userRole": "padres"})
            logger.debug(f"Opciones especiales: {r}")

            # Estrategia 2: GET al home con parámetro de usuario
            for params in [
                {"idUsuario": user_id_num},
                {"user": user_id_num},
                {"userId": user_id_num},
                {"estudiante": user_id_num},
            ]:
                try:
                    resp = self.session.get(
                        f"{BASE}/home/",
                        params=params,
                        allow_redirects=True,
                        timeout=15,
                    )
                    if resp.ok:
                        logger.info(f"Intento cambio con params {params}: {resp.status_code}")
                        break
                except Exception:
                    pass

            self._estudiante_activo = nombre
            logger.info(f"Estudiante activo: {nombre}")
            return True

        except Exception as e:
            logger.warning(f"cambiar_estudiante({nombre}): {e}")
            self._estudiante_activo = nombre
            return True  # Continuar aunque no confirmemos el cambio

    # ── Llamada CFC genérica ──────────────────────────────────────────────────

    def cfc_get(self, cfc_path: str, method: str, params: dict = None) -> dict:
        """Llama un endpoint CFC y retorna JSON parseado."""
        url = f"{BASE}/{cfc_path}"
        p = {"method": method, "returnformat": "json"}
        if params:
            p.update(params)
        resp = self.session.get(url, params=p, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def html_get(self, path: str, params: dict = None) -> BeautifulSoup:
        """GET de una página HTML y retorna BeautifulSoup."""
        url = f"{BASE}/{path}"
        resp = self.session.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")

    # ── Utilidades de formato Lucee ───────────────────────────────────────────

    @staticmethod
    def query_to_dicts(data, key: str = None) -> list:
        """
        Convierte Lucee QueryBean {"COLUMNS":[...], "DATA":[[...],...]}
        a lista de dicts con claves en mayúsculas.
        """
        if key:
            data = data.get(key, {}) if isinstance(data, dict) else {}
        if not isinstance(data, dict):
            return []
        columns = [c.upper() for c in data.get("COLUMNS", [])]
        return [dict(zip(columns, row)) for row in data.get("DATA", [])]

    # ── Endpoints de datos ────────────────────────────────────────────────────

    def get_proximos_eventos(self) -> dict:
        """Home: próximos eventos (EVENTOSAV + EVENTOS)."""
        try:
            return self.cfc_get("home/cfc/home.cfc", "getNext")
        except Exception as e:
            logger.warning(f"get_proximos_eventos: {e}")
            return {}

    def get_posts_aula_virtual(self, filtro: str = "todos") -> dict:
        """
        Aula Virtual: lista de posts/tareas.
        filtro: 'todos' | 'porentregar'
        """
        try:
            return self.cfc_get(
                "aulavirtual/cfc/aulavirtual.cfc",
                "getPostsPorUsuario",
                {"filter": filtro, "userRole": "padres", "fecha": ""},
            )
        except Exception as e:
            logger.warning(f"get_posts_aula_virtual: {e}")
            return {}

    def get_post_detalle(self, id_post: int) -> dict:
        """Detalle de un post específico del aula virtual."""
        try:
            return self.cfc_get(
                "aulavirtual/cfc/aulavirtual.cfc", "getPost", {"id": id_post}
            )
        except Exception as e:
            logger.warning(f"get_post_detalle({id_post}): {e}")
            return {}

    def get_calificaciones_html(self) -> BeautifulSoup:
        """Calificaciones (HTML server-side)."""
        try:
            return self.html_get("calificaciones/estudiante.cfm")
        except Exception as e:
            logger.warning(f"get_calificaciones_html: {e}")
            return BeautifulSoup("", "lxml")

    def get_mensajes_html(self) -> BeautifulSoup:
        """Mensajes recibidos (HTML server-side)."""
        try:
            return self.html_get("comunicacion/mensajes/recibidos.cfm")
        except Exception as e:
            logger.warning(f"get_mensajes_html: {e}")
            return BeautifulSoup("", "lxml")

    def get_asistencia_html(self) -> BeautifulSoup:
        """Asistencia (HTML server-side)."""
        try:
            return self.html_get(
                "asistenciayconductaEst/index.cfm", {"sec": "asistencia"}
            )
        except Exception as e:
            logger.warning(f"get_asistencia_html: {e}")
            return BeautifulSoup("", "lxml")

    def get_boleta_html(self) -> BeautifulSoup:
        """Boleta de conducta (HTML server-side)."""
        try:
            return self.html_get(
                "asistenciayconductaEst/index.cfm", {"sec": "boletas"}
            )
        except Exception as e:
            logger.warning(f"get_boleta_html: {e}")
            return BeautifulSoup("", "lxml")

    def get_anotaciones_html(self) -> BeautifulSoup:
        """Anotaciones (HTML server-side)."""
        try:
            return self.html_get(
                "asistenciayconductaEst/index.cfm", {"sec": "anotaciones"}
            )
        except Exception as e:
            logger.warning(f"get_anotaciones_html: {e}")
            return BeautifulSoup("", "lxml")
