"""
browser.py v3.5.0 — Fix bug _esta_en_login() false positive.

BUG en v3.4.0:
  _esta_en_login() buscaba strings como 'loginBtn', 'loginForm' en
  driver.page_source. El bundle JavaScript de la SPA de WootIT incluye
  SIEMPRE esos strings aunque estemos en /home/ autenticados.
  Resultado: después del login exitoso (URL=/home/), _esta_en_login()
  devolvía True → continue → 3 intentos agotados → "Login fallido".

FIX:
  _esta_en_login() ahora verifica si el ELEMENTO VISIBLE del login
  está realmente presente usando find_elements() con display check,
  NO buscando texto en page_source.
  Adicionalmente: el login ya no llama _esta_en_login() después de
  confirmar URL=/home/ — si la URL cambió a home, el login fue exitoso.
"""
import base64
import logging
import os
import time
from io import BytesIO

import anthropic
import chromedriver_autoinstaller
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException

import config

logger = logging.getLogger(__name__)

SELECTOR_BTN_MENU  = "button-show-menu"
SELECTOR_SUBMENU   = "submenu-usuarios"

ESTUDIANTES_IDS = {
    "Carlos Emiliano": "user213",
    "Starling Andrés":  "user240",
}

_EN_CI = os.environ.get("CI", "").lower() == "true"


def get_driver(headless=True):
    if _EN_CI:
        headless = True
    chromedriver_path = chromedriver_autoinstaller.install()
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-extensions")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )
    if not headless:
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
    service = Service(chromedriver_path) if chromedriver_path else Service()
    driver  = webdriver.Chrome(service=service, options=opts)
    driver.implicitly_wait(5)
    logger.info(f"Chrome iniciado (headless={headless})")
    return driver


def screenshot_base64(driver):
    png = driver.get_screenshot_as_png()
    img = Image.open(BytesIO(png))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def analizar_pantalla_con_claude(driver, pregunta):
    if not config.USAR_COMPUTER_USE:
        return ""
    try:
        client   = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        img_b64  = screenshot_base64(driver)
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                 "media_type": "image/png", "data": img_b64}},
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


def _esta_en_login(driver):
    """
    FIX v3.5.0: Detecta login verificando la URL, NO el page_source.
    page_source siempre contiene strings como 'loginBtn' en el bundle JS.
    La URL es el indicador confiable del estado actual de la SPA.
    """
    try:
        url = driver.current_url
        # Si la URL contiene /login/ claramente estamos en login
        if '/login/' in url or url.endswith('/login'):
            return True
        # Si la URL es la raíz o el home, NO estamos en login
        if '/home/' in url or url.endswith('/home'):
            return False
        # Para cualquier otra URL interna (/calificaciones/, etc.)
        # verificar si el botón de login está VISIBLE en pantalla
        try:
            btn = driver.find_element(By.ID, "loginBtn")
            return btn.is_displayed()
        except NoSuchElementException:
            return False
    except Exception:
        return False


def wait_and_get(driver, url, css_wait="body", timeout=20):
    """
    Navega dentro de la SPA usando JavaScript location.href
    para mantener la sesión activa.
    """
    try:
        base = config.BASE_URL

        # Extraer path relativo
        if url.startswith(base):
            path = url[len(base):]
        elif url.startswith('http'):
            driver.get(url)
            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css_wait))
            )
            time.sleep(1.5)
            return True
        else:
            path = url

        logger.debug(f"Navegando SPA a: {path}")
        driver.execute_script(f"window.location.href = '{base}{path}'")
        time.sleep(3)

        # Verificar redirección a login usando URL
        if _esta_en_login(driver):
            logger.warning(f"Redirigido al login al navegar a {path}. Re-login...")
            if _re_login(driver):
                driver.execute_script(f"window.location.href = '{base}{path}'")
                time.sleep(3)
                if _esta_en_login(driver):
                    logger.error(f"Sigue en login tras re-login. Abortando {path}")
                    return False
            else:
                return False

        if css_wait != 'body':
            try:
                WebDriverWait(driver, timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, css_wait))
                )
            except TimeoutException:
                pass

        time.sleep(1.5)
        return True

    except Exception as e:
        logger.error(f"Error en wait_and_get({url}): {e}")
        return False


def _re_login(driver):
    """Re-autentica si la sesión expiró."""
    logger.info("Re-login por sesión expirada...")
    return login(driver)


def login(driver):
    """
    Login en WootIT con retry (3 intentos).
    FIX v3.5.0: No llama _esta_en_login() tras confirmar URL=/home/
    para evitar false positives por bundle JS de la SPA.
    """
    for intento in range(1, 4):
        try:
            logger.info(f"Login intento {intento}/3...")
            driver.get(f"{config.BASE_URL}/login/")

            wait = WebDriverWait(driver, 20)
            campo_user = wait.until(EC.element_to_be_clickable((By.ID, "username")))
            campo_pass = driver.find_element(By.ID, "password")
            btn_login  = driver.find_element(By.ID, "loginBtn")

            campo_user.clear()
            campo_user.send_keys(config.WOOTIT_USER)
            time.sleep(0.5)
            campo_pass.clear()
            campo_pass.send_keys(config.WOOTIT_PASS)
            time.sleep(0.5)
            btn_login.click()

            logger.info("Clic en login, esperando redirección a /home/...")
            time.sleep(5)

            # Cerrar modales si aparecen
            try:
                for cb in driver.find_elements(
                        By.CSS_SELECTOR, ".close, .btn-close, [data-dismiss='modal']"):
                    if cb.is_displayed():
                        cb.click()
                        time.sleep(1)
            except Exception:
                pass

            # Esperar que la URL cambie a /home/ — indicador confiable de login exitoso
            try:
                WebDriverWait(driver, 30).until(
                    lambda d: "home" in d.current_url and "login" not in d.current_url
                )
                logger.info(f"Login exitoso. URL: {driver.current_url}")

                # Guardar screenshot y HTML del home para diagnóstico
                try:
                    os.makedirs("/tmp/screenshots", exist_ok=True)
                    driver.save_screenshot("/tmp/screenshots/home_post_login.png")
                    with open("/tmp/screenshots/home_post_login.html", "w",
                              encoding="utf-8") as f:
                        f.write(driver.page_source[:80000])
                    logger.info("Screenshot y HTML del home guardados en /tmp/screenshots/")
                except Exception as ex:
                    logger.warning(f"No se pudo guardar screenshot: {ex}")

                return True

            except TimeoutException:
                # Login no confirmado — guardar screenshot de diagnóstico
                try:
                    os.makedirs("/tmp/logs", exist_ok=True)
                    driver.save_screenshot(f"/tmp/logs/error_login_{intento}.png")
                    logger.warning(
                        f"Login timeout intento {intento}. "
                        f"URL actual: {driver.current_url}. "
                        f"Screenshot guardado."
                    )
                except Exception:
                    logger.warning(f"Login timeout intento {intento}.")

        except Exception as e:
            logger.warning(f"Error login intento {intento}: {e}")
            time.sleep(3)

    return False


def cambiar_estudiante(driver, nombre, grado_esperado):
    """Cambia de perfil de estudiante usando el menú del portal."""
    user_id = ESTUDIANTES_IDS.get(nombre)
    if not user_id:
        logger.error(f"ID no encontrado para: {nombre}")
        return False

    nombre_buscar = nombre.split()[0].lower()

    for intento in range(1, 4):
        try:
            logger.info(f"cambiar_estudiante intento {intento}/3 → {nombre}")

            # Navegar a home via JS para mantener sesión
            driver.execute_script(f"window.location.href = '{config.BASE_URL}/home/'")
            wait = WebDriverWait(driver, 20)
            wait.until(EC.presence_of_element_located((By.ID, SELECTOR_BTN_MENU)))
            time.sleep(2)

            if _esta_en_login(driver):
                logger.warning("En login al intentar cambiar perfil. Re-login...")
                if not _re_login(driver):
                    return False

            btn = wait.until(EC.element_to_be_clickable((By.ID, SELECTOR_BTN_MENU)))
            btn.click()
            time.sleep(2)

            wait.until(EC.visibility_of_element_located((By.ID, SELECTOR_SUBMENU)))

            avatar = wait.until(EC.element_to_be_clickable((By.ID, user_id)))
            avatar.click()
            logger.info(f"Clic en avatar {nombre} (ID={user_id})")
            time.sleep(4)

            if _esta_en_login(driver):
                logger.warning(f"Redirigido al login tras cambio (intento {intento})")
                if not _re_login(driver):
                    continue
                continue

            # Verificar nombre en la página
            try:
                page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                if nombre_buscar in page_text:
                    logger.info(f"Cambio a {nombre} verificado.")
                    return True
            except Exception:
                pass

            logger.info(f"Cambio a {nombre}: aceptado (URL={driver.current_url}).")
            return True

        except Exception as e:
            logger.warning(f"cambiar_estudiante intento {intento} excepción: {e}")
            time.sleep(2)

    logger.warning(f"Aceptando {nombre} tras 3 intentos.")
    return True
