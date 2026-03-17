"""
token_refresh.py — Renovación automática del WOOTITAPITOKEN.

PROBLEMA: WOOTITAPITOKEN expira en ~15 minutos.
SOLUCIÓN: Usar WOOTITAPIREFRESHTOKEN (duración larga) para obtener
          un nuevo token antes de cada run.

FLUJO:
1. Al iniciar, verificar si WOOTITAPITOKEN está expirado
2. Si expiró → llamar al endpoint de refresh con WOOTITAPIREFRESHTOKEN
3. Actualizar el secret WOOTIT_COOKIES en GitHub via API
4. Continuar con las cookies renovadas

Las cookies de sesión Lucee (cfid, cftoken, WOOTA, WOOTP, WOOTU)
son de larga duración y NO necesitan renovarse.
Solo WOOTITAPITOKEN necesita refresh frecuente.
"""
import base64
import json
import logging
import os
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

BACKEND = "https://backend.wootit.com"
BASE    = "https://www.wootit.com/adventistacademy"


def _jwt_expirado(token: str, margen_segundos: int = 60) -> bool:
    """Retorna True si el JWT está expirado o expira en menos de margen_segundos."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return True
        payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
        data = json.loads(base64.b64decode(payload).decode("utf-8"))
        exp = data.get("exp", 0)
        ahora = int(time.time())
        expirado = ahora >= (exp - margen_segundos)
        if expirado:
            exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
            logger.info(f"JWT expirado: exp={exp_dt.isoformat()}, ahora={datetime.now(tz=timezone.utc).isoformat()}")
        return expirado
    except Exception as e:
        logger.warning(f"Error verificando JWT: {e}")
        return True  # Asumir expirado si no se puede verificar


def _parsear_cookies(cookie_str: str) -> dict:
    cookies = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            cookies[k.strip()] = v.strip()
    return cookies


def _cookies_a_string(cookies: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def renovar_token(cookie_str: str) -> str:
    """
    Intenta renovar el WOOTITAPITOKEN usando el WOOTITAPIREFRESHTOKEN.
    Retorna el cookie_str actualizado, o el original si falla.
    """
    cookies = _parsear_cookies(cookie_str)
    jwt_actual = cookies.get("WOOTITAPITOKEN", "")
    refresh_token = cookies.get("WOOTITAPIREFRESHTOKEN", "")

    if not _jwt_expirado(jwt_actual):
        logger.info("✅ JWT vigente — no necesita refresh")
        return cookie_str

    if not refresh_token:
        logger.error("❌ WOOTITAPIREFRESHTOKEN no encontrado en cookies")
        return cookie_str

    logger.info(f"🔄 Renovando JWT con refreshToken: {refresh_token[:20]}...")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })

    # Estrategia 1: backend.wootit.com/v1/auth/refresh (REST API)
    for endpoint in [
        f"{BACKEND}/v1/auth/refresh",
        f"{BACKEND}/v1/auth/token/refresh",
        f"{BACKEND}/v1/refresh",
        f"{BACKEND}/v1/users/refresh",
    ]:
        try:
            r = session.post(endpoint, json={"refreshToken": refresh_token}, timeout=10)
            if r.status_code == 200:
                data = r.json()
                nuevo_jwt = (data.get("token") or data.get("accessToken") or
                             data.get("WOOTITAPITOKEN") or data.get("jwt") or "")
                if nuevo_jwt:
                    cookies["WOOTITAPITOKEN"] = nuevo_jwt
                    nuevo_refresh = data.get("refreshToken") or data.get("WOOTITAPIREFRESHTOKEN")
                    if nuevo_refresh:
                        cookies["WOOTITAPIREFRESHTOKEN"] = nuevo_refresh
                    nuevo_str = _cookies_a_string(cookies)
                    logger.info(f"✅ JWT renovado via {endpoint}")
                    _actualizar_secret_github(nuevo_str)
                    return nuevo_str
        except Exception as e:
            logger.debug(f"  {endpoint}: {e}")

    # Estrategia 2: CFC de login de WootIT
    for endpoint in [
        f"{BASE}/login/cfc/login.cfc",
        f"{BASE}/cfc/login.cfc",
    ]:
        for method in ["refreshToken", "renovarToken", "refresh"]:
            try:
                r = session.post(endpoint, data={
                    "method": method,
                    "returnformat": "json",
                    "refreshToken": refresh_token,
                    "WOOTITAPIREFRESHTOKEN": refresh_token,
                }, timeout=10)
                if r.status_code == 200 and r.text.strip():
                    data = r.json()
                    nuevo_jwt = (data.get("token") or data.get("WOOTITAPITOKEN") or "")
                    if nuevo_jwt:
                        cookies["WOOTITAPITOKEN"] = nuevo_jwt
                        nuevo_str = _cookies_a_string(cookies)
                        logger.info(f"✅ JWT renovado via CFC {method}")
                        _actualizar_secret_github(nuevo_str)
                        return nuevo_str
            except Exception as e:
                logger.debug(f"  {method}: {e}")

    # Estrategia 3: Re-login directo con credenciales
    usuario = os.environ.get("WOOTIT_USER", "")
    password = os.environ.get("WOOTIT_PASS", "")
    if usuario and password:
        try:
            s2 = requests.Session()
            s2.headers.update({"User-Agent": "Mozilla/5.0"})
            # Cargar cookies de sesión Lucee (las que no expiran)
            for name in ["cfid", "cftoken", "QUSUARIO", "WOOTA", "WOOTP",
                         "WOOTU", "WOOTAUTOLOG", "codigoe-_zldp", "codigoe-_zldt"]:
                if name in cookies:
                    s2.cookies.set(name, cookies[name], domain="www.wootit.com")

            r = s2.get(f"{BASE}/login/", timeout=15)
            r = s2.post(f"{BASE}/login/",
                        data={"usuario": usuario, "contrasena": password},
                        allow_redirects=True, timeout=20)
            if "home" in r.url:
                # Extraer nuevo JWT de las cookies de respuesta
                nuevas = {c.name: c.value for c in s2.cookies}
                nuevo_jwt = nuevas.get("WOOTITAPITOKEN", "")
                if nuevo_jwt:
                    cookies.update(nuevas)
                    nuevo_str = _cookies_a_string(cookies)
                    logger.info("✅ JWT renovado via re-login")
                    _actualizar_secret_github(nuevo_str)
                    return nuevo_str
        except Exception as e:
            logger.warning(f"Re-login fallido: {e}")

    logger.error("❌ No se pudo renovar el JWT. Usando cookies originales.")
    return cookie_str


def _actualizar_secret_github(nuevo_cookie_str: str):
    """
    Actualiza el secret WOOTIT_COOKIES en GitHub via API REST.
    Requiere GITHUB_TOKEN con permisos de secrets.
    """
    github_token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "chernandezhidalgo/colegiocr")

    if not github_token:
        logger.warning("GITHUB_TOKEN no disponible — secret no actualizado automáticamente")
        logger.info("Para actualizar manualmente: Settings → Secrets → WOOTIT_COOKIES")
        return

    try:
        import base64
        from nacl import encoding, public as nacl_public

        # Obtener public key del repo para encriptar el secret
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        r = requests.get(
            f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
            headers=headers, timeout=10
        )
        r.raise_for_status()
        key_data = r.json()
        public_key = key_data["key"]
        key_id     = key_data["key_id"]

        # Encriptar el valor
        pk = nacl_public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
        box = nacl_public.SealedBox(pk)
        encrypted = base64.b64encode(
            box.encrypt(nuevo_cookie_str.encode("utf-8"))
        ).decode("utf-8")

        # Actualizar el secret
        r2 = requests.put(
            f"https://api.github.com/repos/{repo}/actions/secrets/WOOTIT_COOKIES",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": key_id},
            timeout=10
        )
        if r2.status_code in (201, 204):
            logger.info("✅ Secret WOOTIT_COOKIES actualizado en GitHub automáticamente")
        else:
            logger.warning(f"GitHub API: {r2.status_code} — {r2.text[:100]}")

    except ImportError:
        logger.warning("PyNaCl no instalado — secret no actualizado. pip install pynacl")
    except Exception as e:
        logger.warning(f"Error actualizando secret GitHub: {e}")
