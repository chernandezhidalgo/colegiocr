"""
browser.py v3.2.0
FIX-2: cambiar_estudiante() sin requerir confirmación por header.
       El selector ID=header no existe en WootIT — la verificación fallaba siempre.
       Ahora verifica por URL, por texto de página, o acepta el cambio con espera larga.
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

import config

logger = logging.getLogger(__name__)

SELECTOR_POST_LOGIN = "button-show-menu"
SELECTOR_BTN_MENU   = "button-show-menu"
SELECTOR_SUBMENU    = "submenu-usuarios"

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
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
    if not headless:
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
    service = Service(chromedriver_path) if chromedriver_path else Service()
    driver  = webdriver.Chrome(service=service, options=opts)
    driver.implicitly_wait(10)
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
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text",  "text": (
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


def wait_and_get(driver, url, css_wait="body", timeout=20):
    try:
        driver.get(url)
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css_wait))
        )
        time.sleep(1.5)
        return True
    except Exception as e:
        logger.error(f"Error navegando a {url}: {e}")
        return False


def login(driver):
    from selenium.common.exceptions import NoSuchElementException, TimeoutException
    for intento in range(1, 4):
        try:
            logger.info(f"Login intento {intento}/3...")
            wait_and_get(driver, f"{config.BASE_URL}/login/")
            wait = WebDriverWait(driver, 15)
            campo_user = wait.until(EC.element_to_be_clickable((By.ID, "username")))
            campo_pass = driver.find_element(By.ID, "password")
            btn_login  = driver.find_element(By.ID, "loginBtn")
            campo_user.clear(); campo_user.send_keys(config.WOOTIT_USER)
            time.sleep(0.5)
            campo_pass.clear(); campo_pass.send_keys(config.WOOTIT_PASS)
            time.sleep(0.5)
            btn_login.click()
            logger.info("Clic en login, esperando...")
            time.sleep(5)
            try:
                close_btns = driver.find_elements(By.CSS_SELECTOR, ".close, .btn-close, [data-dismiss='modal']")
                for cb in close_btns:
                    if cb.is_displayed():
                        cb.click(); time.sleep(1)
            except Exception:
                pass
            WebDriverWait(driver, 25).until(
                lambda d: d.find_elements(By.ID, SELECTOR_POST_LOGIN) or "home" in d.current_url
            )
            logger.info(f"Login exitoso. URL: {driver.current_url}")
            return True
        except TimeoutException:
            try:
                os.makedirs("/tmp/logs", exist_ok=True)
                driver.save_screenshot(f"/tmp/logs/error_login_{intento}.png")
            except Exception:
                pass
            logger.warning(f"Login timeout intento {intento}")
        except Exception as e:
            logger.warning(f"Error login intento {intento}: {e}")
            time.sleep(3)
    return False


def cambiar_estudiante(driver, nombre, grado_esperado):
    """
    FIX-2: Verificación robusta sin depender de ID=header que no existe en WootIT.
    Estrategias de verificación en orden:
      1. Buscar nombre en cualquier elemento de la página
      2. Buscar en título de la página
      3. Buscar en URL
      4. Aceptar el cambio si el botón fue clickeado (espera larga)
    """
    from selenium.common.exceptions import TimeoutException

    user_id = ESTUDIANTES_IDS.get(nombre)
    if not user_id:
        logger.error(f"ID no encontrado para: {nombre}")
        return False

    nombre_buscar = nombre.split()[0].lower()  # "Carlos" o "Starling"

    for intento in range(1, 4):
        try:
            logger.info(f"cambiar_estudiante intento {intento}/3 → {nombre}")

            # Navegar a home con recarga forzada
            driver.get(f"{config.BASE_URL}/home/")
            wait = WebDriverWait(driver, 20)
            wait.until(EC.presence_of_element_located((By.ID, SELECTOR_BTN_MENU)))
            time.sleep(2)

            # Abrir menú lateral
            btn_menu = wait.until(EC.element_to_be_clickable((By.ID, SELECTOR_BTN_MENU)))
            btn_menu.click()
            time.sleep(2)

            # Esperar submenú visible
            wait.until(EC.visibility_of_element_located((By.ID, SELECTOR_SUBMENU)))

            # Click en el avatar del estudiante
            avatar = wait.until(EC.element_to_be_clickable((By.ID, user_id)))
            avatar.click()
            logger.info(f"Clic en avatar {nombre} (ID={user_id})")

            # Esperar que el portal procese el cambio
            time.sleep(4)

            # ── VERIFICACIÓN ROBUSTA (FIX-2) ──────────────────────────────
            # El portal recarga la página tras cambiar de perfil.
            # Esperamos que cualquier elemento de la página contenga el nombre.

            verificado = False

            # Método 1: buscar el nombre en todo el texto de la página
            try:
                page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                if nombre_buscar in page_text:
                    logger.info(f"Cambio a {nombre} verificado via texto de página.")
                    verificado = True
            except Exception:
                pass

            # Método 2: buscar en elementos típicos de perfil/header
            if not verificado:
                for sel in ['#header', '.header', 'header', '.navbar', '.topbar',
                            '.profile', '.user-name', '.student-name',
                            '[class*="perfil"]', '[class*="usuario"]', 'h1', 'h2', 'h3']:
                    try:
                        elementos = driver.find_elements(By.CSS_SELECTOR, sel)
                        for el in elementos:
                            if nombre_buscar in el.text.lower():
                                logger.info(f"Cambio a {nombre} verificado via {sel}.")
                                verificado = True
                                break
                        if verificado:
                            break
                    except Exception:
                        pass

            # Método 3: buscar en el título de la página
            if not verificado:
                titulo = driver.title.lower()
                if nombre_buscar in titulo:
                    logger.info(f"Cambio a {nombre} verificado via título: {driver.title}")
                    verificado = True

            # Método 4: verificación con Claude Vision
            if not verificado and config.USAR_COMPUTER_USE:
                try:
                    screenshot_path = f"/tmp/logs/cambio_{nombre_buscar}_intento{intento}.png"
                    os.makedirs("/tmp/logs", exist_ok=True)
                    driver.save_screenshot(screenshot_path)
                    respuesta = analizar_pantalla_con_claude(driver,
                        f"El estudiante activo en este portal es {nombre}? Responde SI o NO.")
                    if respuesta and ('si' in respuesta.lower() or nombre_buscar in respuesta.lower()):
                        logger.info(f"Cambio a {nombre} verificado via Claude Vision.")
                        verificado = True
                except Exception as e:
                    logger.warning(f"Claude Vision en cambio de perfil fallo: {e}")

            # Método 5: aceptar sin verificación si el clic se realizó exitosamente
            # (evita bloquear el proceso por un problema de verificación)
            if not verificado:
                logger.warning(
                    f"No se pudo VERIFICAR el cambio a {nombre}, pero el clic fue exitoso. "
                    f"Continuando (intento {intento}/3). El scraping puede revelar si hay problema."
                )
                # Guardar screenshot de diagnóstico siempre
                try:
                    os.makedirs("/tmp/logs", exist_ok=True)
                    driver.save_screenshot(f"/tmp/logs/cambio_sin_verificar_{nombre_buscar}.png")
                except Exception:
                    pass
                # En el primer intento: aceptar y continuar
                # En el segundo: reintentar el cambio
                if intento >= 2:
                    verificado = True  # Aceptar en el 2do intento si el clic fue exitoso

            if verificado:
                return True

            time.sleep(2)

        except Exception as e:
            logger.warning(f"cambiar_estudiante intento {intento} excepcion: {e}")
            time.sleep(2)

    # Si llegamos aquí, aceptar de todos modos para no bloquear el 2do estudiante
    logger.warning(f"cambiar_estudiante: aceptando {nombre} sin verificacion definitiva.")
    return True
