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

# Importar módulo de refresh (si está disponible)
try:
    from modules.token_refresh import renovar_token
    _REFRESH_DISPONIBLE = True
except ImportError:
    _REFRESH_DISPONIBLE = False

TZ_CR = ZoneInfo("America/Costa_Rica")
BASE         = config.BASE_URL
BACKEND      = "https://backend.wootit.com"

ESTUDIANTES_IDS = {
    "Carlos Emiliano": "user213",  # ID del avatar en menú (changeSon)
    "Starling Andrés":  "user240", # ID del avatar en menú (changeSon)
}

ESTUDIANTES_NUM = {
    "Carlos Emiliano": 213,  # ID de changeSon()
    "Starling Andrés":  240, # ID de changeSon()
}

# QUSUARIO = ID real de sesión (cambia al seleccionar hijo)
# 534 confirmado para Starling vía DevTools Application → Cookies
ESTUDIANTES_QUSUARIO = {
    "Carlos Emiliano": 480,   # Confirmado: QUSUARIO=480 cuando Carlos está activo
    "Starling Andrés":  534,
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
        self._qusuario_activo = None
        self._cookies_dict = {}

    def login(self) -> bool:
        cookie_str = os.environ.get("WOOTIT_COOKIES", "").strip()
        if not cookie_str:
            logger.error("❌ Secret WOOTIT_COOKIES no configurado.")
            return False

        # Renovar JWT si está expirado antes de proceder
        if _REFRESH_DISPONIBLE:
            cookie_str = renovar_token(cookie_str)

        self._cookies_dict = _parsear_cookie_string(cookie_str)
        for name, value in self._cookies_dict.items():
            self.session.cookies.set(name, value, domain="www.wootit.com")

        logger.info(f"🍪 Cookies cargadas: {list(self._cookies_dict.keys())}")

        # Decodificar JWT para ver qué usuario/estudiante tiene la sesión
        jwt = self._cookies_dict.get("WOOTITAPITOKEN", "")
        if jwt:
            payload = _decodificar_jwt(jwt)
            logger.info(f"🔑 JWT payload: {payload}")
            # Agregar JWT como header Authorization para CFCs que lo requieran
            self.session.headers.update({
                "Authorization": f"Bearer {jwt}",
            })

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
        Cambia el estudiante activo via el endpoint confirmado del portal:
        includes/procesos.cfm?changeStudent=1&id=<userId>

        Esto actualiza la sesión server-side de Lucee (QUSUARIO cambia)
        para que los endpoints HTML devuelvan datos del estudiante correcto.
        """
        user_num = ESTUDIANTES_NUM.get(nombre)
        qusuario = ESTUDIANTES_QUSUARIO.get(nombre)
        if not user_num:
            logger.error(f"ID no encontrado para: {nombre}")
            return False

        try:
            resp = self.session.get(
                f"{BASE}/includes/procesos.cfm",
                params={"changeStudent": 1, "id": user_num},
                allow_redirects=True,
                timeout=15,
            )
            logger.info(f"changeSon({user_num}): {resp.status_code} | url={resp.url}")
            # Verificar que QUSUARIO cambió en las cookies de respuesta
            nuevas_cookies = {c.name: c.value for c in resp.cookies}
            if "QUSUARIO" in nuevas_cookies:
                nuevo_qusuario = nuevas_cookies["QUSUARIO"]
                logger.info(f"QUSUARIO actualizado: {nuevo_qusuario}")
                self.session.cookies.set("QUSUARIO", nuevo_qusuario, domain="www.wootit.com")
                # Guardar para uso en endpoints
                self._qusuario_activo = nuevo_qusuario
            elif qusuario:
                self._qusuario_activo = str(qusuario)
                logger.info(f"QUSUARIO esperado: {qusuario}")
        except Exception as e:
            logger.warning(f"changeSon error: {e}")
            self._qusuario_activo = str(qusuario) if qusuario else None

        self._user_id_activo = user_num
        self._estudiante_activo = nombre
        logger.info(f"✅ Estudiante activo: {nombre} (changeSon={user_num}, QUSUARIO={self._qusuario_activo})")
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

    def get_mensajes_json(self) -> dict:
        """
        Mensajes via CFC. Endpoint confirmado del Network:
        comunicacion/cfc/mensajes.cfc
        userId = QUSUARIO activo (cambia al seleccionar estudiante).
        """
        qusuario = self._qusuario_activo or self._cookies_dict.get("QUSUARIO", "480")
        # Probar métodos en orden de probabilidad
        for method in ["getRecibidos", "getMensajes", "getAll",
                       "getMensajesRecibidos", "getTodos"]:
            try:
                r = self.session.get(
                    f"{BASE}/comunicacion/cfc/mensajes.cfc",
                    params={"method": method, "returnformat": "json",
                            "userId": qusuario},
                    timeout=20,
                )
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, dict) and "COLUMNS" in data:
                        logger.info(f"✅ mensajes.cfc/{method}: {len(data.get('DATA',[]))} filas")
                        return data
                    elif isinstance(data, list) and data:
                        logger.info(f"✅ mensajes.cfc/{method} (list): {len(data)} items")
                        return {"COLUMNS": list(data[0].keys()) if data else [],
                                "DATA": [[v for v in row.values()] for row in data]}
            except Exception as e:
                logger.debug(f"mensajes.cfc/{method}: {e}")
        logger.warning("mensajes.cfc: ningún método devolvió datos")
        return {}

    def get_cursos_estudiante(self) -> list:
        """
        Obtiene lista de cursos del estudiante.
        Paso 1 del flujo de calificaciones: estudiante.cfm carga los cursos,
        luego estudianteDetalles.cfm?idCurso=X&idEst=Y carga notas de cada curso.
        """
        user = self._user_id_activo or 213
        cfc = "calificaciones/cfc/calificaciones.cfc"
        for method in ["getCursos", "getMaterias", "getCursosEstudiante",
                       "getEstudiante", "getCursosAlumno", "getAll"]:
            for params in [{"idEst": user}, {"userId": user}, {"idUsuario": user}]:
                try:
                    r = self.session.get(f"{BASE}/{cfc}",
                        params={"method": method, "returnformat": "json", **params},
                        timeout=10)
                    if r.status_code == 200 and "COLUMNS" in r.text[:200]:
                        data = r.json()
                        rows = WootITClient.query_to_dicts_static(data)
                        if rows:
                            logger.info(f"✅ getCursos/{method}: {len(rows)} cursos | "
                                        f"cols={list(rows[0].keys())[:6]}")
                            return rows
                except Exception:
                    pass
        return []

    def get_calificaciones_curso(self, id_curso: int) -> list:
        """
        Obtiene calificaciones de un curso específico.
        Paso 2: estudianteDetalles.cfm?idCurso=X&idEst=Y
        """
        user = self._user_id_activo or 213
        cfc = "calificaciones/cfc/calificaciones.cfc"
        for method in ["getCalificaciones", "getNotas", "getDetalles",
                       "getCalificacionesEstudiante", "getNota", "getAll"]:
            try:
                r = self.session.get(f"{BASE}/{cfc}",
                    params={"method": method, "returnformat": "json",
                            "idCurso": id_curso, "idEst": user},
                    timeout=10)
                if r.status_code == 200 and "COLUMNS" in r.text[:200]:
                    data = r.json()
                    rows = WootITClient.query_to_dicts_static(data)
                    if rows:
                        logger.info(f"✅ getCalificaciones curso {id_curso}/{method}: "
                                    f"{len(rows)} filas")
                        return rows
            except Exception:
                pass
        return []

    def get_calificaciones_json(self) -> dict:
        """
        Calificaciones via CFC — flujo de 2 pasos descubierto:
        1. estudianteDetalles.cfm?idCurso=739&idEst=240
           → parámetros: idEst (estudiante), idCurso (curso)
        2. Primero obtenemos la lista de cursos, luego las notas de cada uno.
        """
        user = self._user_id_activo or 213
        cfc = "calificaciones/cfc/calificaciones.cfc"

        # Intentar endpoint directo primero (más simple)
        methods_directos = ["getCalificaciones", "getNotas", "getEstudiante",
                            "getResumen", "getAll", "getCursos"]
        param_sets = [
            {"idEst": user},
            {"idEst": user, "userId": user},
            {"userId": user},
            {"idUsuario": user},
        ]
        for method in methods_directos:
            for params in param_sets:
                try:
                    r = self.session.get(f"{BASE}/{cfc}",
                        params={"method": method, "returnformat": "json", **params},
                        timeout=10)
                    if r.status_code == 200:
                        text = r.text.strip()
                        if "COLUMNS" in text[:200]:
                            data = r.json()
                            if data.get("DATA"):
                                logger.info(f"✅ CALIFICACIONES directo {method}/"
                                            f"{list(params.keys())}: {len(data['DATA'])} filas")
                                return data
                        elif text not in ("null","","{}","[]","false"):
                            logger.info(f"   cal {method}/{list(params.keys())}: {text[:100]}")
                except Exception:
                    pass

        logger.warning("calificaciones CFC: ningún endpoint respondió con datos")
        return {}

    @staticmethod
    def query_to_dicts_static(data) -> list:
        """Versión estática de query_to_dicts para uso en métodos de instancia."""
        if not isinstance(data, dict):
            return []
        columns = [c.upper() for c in data.get("COLUMNS", [])]
        return [dict(zip(columns, row)) for row in data.get("DATA", [])]

    def get_asistencia_json(self) -> dict:
        """
        Asistencia via CFC con JWT Authorization header.
        """
        user = self._user_id_activo or 213
        paths = [
            "asistenciayconductaEst/cfc/asistencia.cfc",
            "asistenciayconductaEst/cfc/asistenciayconducta.cfc",
            "asistenciayconductaEst/cfc/asisEst.cfc",
            "asistenciayconductaEst/cfc/asistenciaEst.cfc",
            "asistenciayconductaEst/cfc/asistenciayconductaEst.cfc",
        ]
        methods = ["getAsistencia", "getResumen", "getAll",
                   "getAsistenciaEstudiante", "get", "getDetalle",
                   "getAsistenciaAlumno", "getPorcentaje"]
        param_sets = [
            {"idEst": user, "returnformat": "json"},
            {"idEst": user, "userId": user, "returnformat": "json"},
            {"userId": user, "returnformat": "json"},
        ]
        for path in paths:
            for method in methods:
              for params in param_sets:
                try:
                    p = {"method": method, **params}
                    r = self.session.get(
                        f"{BASE}/{path}", params=p,
                        timeout=10,
                    )
                    if r.status_code == 200:
                        text = r.text.strip()
                        if "COLUMNS" in text[:200]:
                            data = r.json()
                            rows = data.get("DATA", [])
                            if rows:
                                logger.info(f"✅ ASISTENCIA {path}/{method}: "
                                            f"{len(rows)} filas | cols={data.get('COLUMNS',[])[:6]}")
                                return data
                        elif text and text not in ("null","","{}","[]"):
                            logger.info(f"   asis {path}/{method}: {text[:80]}")
                except Exception:
                    pass
        logger.warning("asistencia CFC: ningún endpoint respondió con datos")
        return {}

    def get_calificaciones_html(self) -> BeautifulSoup:
        try:
            resp = self.session.get(f"{BASE}/calificaciones/estudiante.cfm", timeout=20)
            resp.raise_for_status()
            html = resp.text
            # Guardar HTML completo para diagnóstico
            import os
            os.makedirs("/tmp/logs", exist_ok=True)
            fname = f"/tmp/logs/calificaciones_{self._user_id_activo}.html"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(html)
            logger.info(f"HTML calificaciones guardado: {fname} ({len(html):,} chars)")
            return BeautifulSoup(html, "lxml")
        except Exception as e:
            logger.warning(f"get_calificaciones_html: {e}")
            return BeautifulSoup("", "lxml")

    def get_asistencia_raw_html(self) -> str:
        """Retorna HTML crudo de asistencia para diagnóstico."""
        try:
            resp = self.session.get(
                f"{BASE}/asistenciayconductaEst/index.cfm",
                params={"sec": "asistencia"}, timeout=20)
            html = resp.text
            import os
            os.makedirs("/tmp/logs", exist_ok=True)
            fname = f"/tmp/logs/asistencia_{self._user_id_activo}.html"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(html)
            logger.info(f"HTML asistencia guardado: {fname} ({len(html):,} chars)")
            return html
        except Exception as e:
            logger.warning(f"get_asistencia_raw_html: {e}")
            return ""

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

    def rest_get(self, path: str, params: dict = None) -> dict:
        """
        GET a la API REST backend.wootit.com/v1/
        Descubierta via interceptor: backend.wootit.com/v1/calendar/next
        """
        url = f"{BACKEND}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.debug(f"REST GET {path}: {e}")
            return {}

    def get_calificaciones_rest(self) -> list:
        """
        Prueba endpoints REST en backend.wootit.com/v1/ para calificaciones.
        """
        user = self._user_id_activo or 213
        endpoints = [
            f"/v1/grades",
            f"/v1/grades/{user}",
            f"/v1/calificaciones",
            f"/v1/calificaciones/{user}",
            f"/v1/students/{user}/grades",
            f"/v1/students/{user}/calificaciones",
            f"/v1/notas",
            f"/v1/notas/{user}",
        ]
        for ep in endpoints:
            try:
                r = self.session.get(f"{BACKEND}{ep}",
                    params={"idEst": user, "userId": user},
                    timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if data and data != [] and data != {}:
                        logger.info(f"✅ REST calificaciones {ep}: {str(data)[:150]}")
                        return data if isinstance(data, list) else [data]
            except Exception:
                pass
        return []

    def get_asistencia_rest(self) -> list:
        """
        Prueba endpoints REST en backend.wootit.com/v1/ para asistencia.
        """
        user = self._user_id_activo or 213
        endpoints = [
            f"/v1/attendance",
            f"/v1/attendance/{user}",
            f"/v1/asistencia",
            f"/v1/asistencia/{user}",
            f"/v1/students/{user}/attendance",
            f"/v1/students/{user}/asistencia",
        ]
        for ep in endpoints:
            try:
                r = self.session.get(f"{BACKEND}{ep}",
                    params={"idEst": user, "userId": user},
                    timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if data and data != [] and data != {}:
                        logger.info(f"✅ REST asistencia {ep}: {str(data)[:150]}")
                        return data if isinstance(data, list) else [data]
            except Exception:
                pass
        return []

    def get_mensajes_rest(self) -> list:
        """
        Prueba endpoints REST en backend.wootit.com/v1/ para mensajes.
        """
        qusuario = self._cookies_dict.get("QUSUARIO", "480")
        endpoints = [
            "/v1/messages",
            f"/v1/messages/{qusuario}",
            "/v1/mensajes",
            f"/v1/mensajes/{qusuario}",
            "/v1/inbox",
        ]
        for ep in endpoints:
            try:
                r = self.session.get(f"{BACKEND}{ep}", timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if data and data != [] and data != {}:
                        logger.info(f"✅ REST mensajes {ep}: {str(data)[:150]}")
                        return data if isinstance(data, list) else [data]
            except Exception:
                pass
        return []
