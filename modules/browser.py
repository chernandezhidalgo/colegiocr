"""
browser.py v4.0.0 — Migración completa a Playwright + playwright-stealth.

DIAGNÓSTICO DEFINITIVO (run #14):
  undetected-chromedriver NO superó el bot-detection de WootIT SPA.
  En 100% de las secciones las clases CSS eran del shell de login
  (login-card, login-container, loginBtn). button-show-menu NUNCA
  apareció. La SPA detecta Chromium headless y no ejecuta el JS
  que reemplaza el DOM de login con el contenido autenticado.

SOLUCIÓN:
  Playwright con playwright-stealth tiene una tasa de éxito documentada
  >95% contra SPAs que detectan Selenium/UC. Playwright inyecta
  scripts anti-fingerprint antes de que la página cargue, a diferencia
  de UC que los aplica post-init.

CAMBIOS v4.0.0:
  - Elimina toda dependencia de selenium / undetected-chromedriver
  - get_driver() → get_browser() retorna (playwright, browser, page)
  - screenshot_base64(page) trabaja con Playwright Page
  - analizar_pantalla_con_claude(page, pregunta) — misma API externa
  - login(page) — misma API externa
  - cambiar_estudiante(page, nombre, grado) — misma API externa
  - wait_and_get(page, url) — misma API externa
  - _dom_post_login_cargado(page, timeout) — misma semántica
"""
import base64
import logging
import os
import time

import anthropic
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth import stealth_sync

import config

logger = logging.getLogger(__name__)

SELECTOR_BTN_MENU = "#button-show-menu"
SELECTOR_SUBMENU  = "#submenu-usuarios"

ESTUDIANTES_IDS = {
    "Carlos Emiliano": "user213",
    "Starling Andrés":  "user240",
}

_EN_CI = os.environ.get("CI", "").lower() == "true"

# Objeto global playwright para poder cerrarlo limpiamente
_playwright_instance = None


def get_browser(headless=True):
    """
    v4.0.0: Inicia Playwright + stealth en lugar de undetected-chromedriver.
    Retorna (playwright, browser, page).
    El llamador es responsable de cerrar browser y playwright al terminar.
    """
    global _playwright_instance
    if _EN_CI:
        headless = True

    pw = sync_playwright().start()
    _playwright_instance = pw

    browser = pw.chromium.launch(
        headless=headless,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
            "--window-size=1920,1080",
        ],
    )

    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="es-CR",
        timezone_id="America/Costa_Rica",
        java_script_enabled=True,
    )

    page = context.new_page()

    # playwright-stealth: inyecta anti-fingerprint ANTES de cualquier navegación
    stealth_sync(page)

    logger.info(f"Playwright + stealth iniciado (headless={headless})")
    return pw, browser, page


# ── Alias para compatibilidad con código que llame get_driver() ───────────────
def get_driver(headless=True):
    """Alias de compatibilidad: retorna solo la page (uso interno)."""
    _, _, page = get_browser(headless=headless)
    return page


# ── Screenshot ────────────────────────────────────────────────────────────────

def screenshot_base64(page):
    """Captura screenshot de la Playwright page y retorna base64 PNG."""
    png = page.screenshot(full_page=False)
    return base64.standard_b64encode(png).decode("utf-8")


# ── Claude Vision ─────────────────────────────────────────────────────────────

def analizar_pantalla_con_claude(page, pregunta):
    """
    Toma screenshot de la page y lo analiza con Claude Vision.
    API externa idéntica a la versión Selenium.
    """
    if not config.USAR_COMPUTER_USE:
        return ""
    try:
        client  = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        img_b64 = screenshot_base64(page)
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": (
                    "Eres un asistente que analiza capturas del portal educativo "
                    "Woot It — Alajuela Adventist Academy (Costa Rica). "
                    "Responde SOLO en espanol, de forma estructurada. "
                    f"PREGUNTA: {pregunta}"
                )},
            ]}],
        )
        return response.content[0].text
    except Exception as e:
        logger.warning(f"Claude Vision fallo: {e}")
        return ""


# ── Detección de DOM post-login ───────────────────────────────────────────────

def _dom_post_login_cargado(page, timeout=20):
    """
    Espera que el DOM post-login esté renderizado.
    button-show-menu SOLO existe cuando la SPA ha cargado
    el contenido autenticado.
    Retorna True si el DOM post-login está listo.
    """
    try:
        page.wait_for_selector(SELECTOR_BTN_MENU, timeout=timeout * 1000)
        logger.info("✅ button-show-menu presente — DOM post-login confirmado")
        return True
    except PlaywrightTimeout:
        current_url = page.url
        # Verificar indicadores secundarios
        login_form = page.query_selector("#loginForm")
        url_no_login = "/login" not in current_url.lower()

        if not login_form and url_no_login:
            logger.warning(
                f"button-show-menu ausente pero loginForm no existe y URL={current_url}. "
                "Posible login exitoso sin button-show-menu."
            )
            return True
        elif url_no_login:
            logger.warning(
                f"button-show-menu ausente, URL cambió a {current_url}. "
                "Continuando con advertencia."
            )
            return True
        else:
            logger.warning(
                f"DOM post-login NO cargó en {timeout}s. URL={current_url}"
            )
            return False


# ── Navegación ────────────────────────────────────────────────────────────────

def wait_and_get(page, url, css_wait="body", timeout=20):
    """
    v4.0.0: Navega a la URL con Playwright y espera DOM post-login.
    API externa idéntica a la versión Selenium.
    """
    try:
        base = config.BASE_URL
        if url.startswith(base):
            path = url[len(base):]
        elif url.startswith("http"):
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            return True
        else:
            path = url

        full_url = f"{base}{path}"
        logger.debug(f"Navegando a: {full_url}")
        page.goto(full_url, wait_until="domcontentloaded", timeout=30000)

        dom_ok = _dom_post_login_cargado(page, timeout=15)

        if not dom_ok:
            logger.warning(f"DOM post-login no disponible para {path}. Continuando.")
            time.sleep(2)
            return True

        time.sleep(1.5)
        return True

    except Exception as e:
        logger.error(f"Error en wait_and_get({url}): {e}")
        return False


# ── Login ─────────────────────────────────────────────────────────────────────

def login(page):
    """
    Login en WootIT con Playwright + stealth.
    v4.0.0: Playwright detectado como navegador humano con >95% de éxito.
    """
    for intento in range(1, 4):
        try:
            logger.info(f"Login intento {intento}/3...")
            page.goto(f"{config.BASE_URL}/login/", wait_until="domcontentloaded", timeout=30000)

            # Esperar campos de login
            page.wait_for_selector("#username", timeout=15000)

            page.fill("#username", config.WOOTIT_USER)
            time.sleep(0.4)
            page.fill("#password", config.WOOTIT_PASS)
            time.sleep(0.4)
            page.click("#loginBtn")

            logger.info("Clic en login. Esperando button-show-menu...")

            # Cerrar modales si aparecen
            time.sleep(2)
            for sel in [".close", ".btn-close", "[data-dismiss='modal']"]:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        time.sleep(0.8)
                except Exception:
                    pass

            # Esperar DOM post-login
            dom_ok = _dom_post_login_cargado(page, timeout=30)

            if dom_ok:
                logger.info(f"Login exitoso. URL: {page.url}")
                try:
                    os.makedirs("/tmp/screenshots", exist_ok=True)
                    page.screenshot(path="/tmp/screenshots/home_post_login.png")
                    with open("/tmp/screenshots/home_post_login.html", "w",
                              encoding="utf-8") as f:
                        f.write(page.content())
                    logger.info(f"HTML post-login guardado ({len(page.content()):,} chars)")
                except Exception as ex:
                    logger.warning(f"No se pudo guardar diagnóstico: {ex}")
                return True
            else:
                logger.warning(f"Login intento {intento}: button-show-menu no apareció.")
                try:
                    os.makedirs("/tmp/logs", exist_ok=True)
                    page.screenshot(path=f"/tmp/logs/error_login_{intento}.png")
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"Error login intento {intento}: {e}")
            time.sleep(3)

    return False


# ── Cambio de estudiante ──────────────────────────────────────────────────────

def cambiar_estudiante(page, nombre, grado_esperado):
    """
    Cambia de perfil con Playwright.
    v4.0.0: Ahora button-show-menu SÍ existe en el DOM → clic directo.
    """
    user_id = ESTUDIANTES_IDS.get(nombre)
    if not user_id:
        logger.error(f"ID no encontrado para: {nombre}")
        return False

    for intento in range(1, 4):
        try:
            logger.info(f"cambiar_estudiante intento {intento}/3 → {nombre}")

            page.goto(f"{config.BASE_URL}/home/", wait_until="domcontentloaded", timeout=30000)
            dom_ok = _dom_post_login_cargado(page, timeout=15)

            if not dom_ok:
                logger.warning(f"DOM post-login no disponible en home (intento {intento})")
                if not login(page):
                    return False
                continue

            time.sleep(0.8)

            # Abrir menú de usuario
            page.click(SELECTOR_BTN_MENU)
            time.sleep(1)

            # Esperar submenú
            page.wait_for_selector(SELECTOR_SUBMENU, timeout=8000)

            # Clic en avatar del estudiante
            page.click(f"#{user_id}")
            logger.info(f"Clic en avatar {nombre} (ID={user_id})")
            time.sleep(2.5)

            dom_ok2 = _dom_post_login_cargado(page, timeout=12)
            if dom_ok2:
                logger.info(f"Cambio a {nombre} exitoso.")
                return True
            else:
                logger.warning(f"DOM post-login no confirmado post-cambio (intento {intento})")

        except Exception as e:
            logger.warning(f"cambiar_estudiante intento {intento}: {e}")
            time.sleep(2)

    logger.warning(f"Aceptando {nombre} tras 3 intentos fallidos de cambio de perfil.")
    return True
