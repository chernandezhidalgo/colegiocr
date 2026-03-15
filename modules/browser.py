"""
browser.py — Gestión del navegador Selenium y análisis visual con Claude API.
v3.1.0 — Chrome compatible con GitHub Actions via browser-actions/setup-chrome.
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

# IDs reales del portal Woot It — Alajuela Adventist Academy
SELECTOR_POST_LOGIN = "button-show-menu"
SELECTOR_BTN_MENU   = "button-show-menu"
SELECTOR_SUBMENU    = "submenu-usuarios"
SELECTOR_HEADER     = "header"

ESTUDIANTES_IDS = {
    "Carlos Emiliano": "user213",
    "Starling Andrés":  "user240",
}

_EN_CI = os.environ.get("CI", "").lower() == "true"


def get_driver(headless: bool = True) -> webdriver.Chrome:
    """
    Crea WebDriver de Chrome.
    En CI (GitHub Actions) siempre headless.
    Usa chromedriver_autoinstaller para garantizar versión compatible.
    """
    if _EN_CI:
        headless = True

    # Instalar chromedriver compatible con la versión de Chrome instalada
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
    opts.add_argument("--remote-debugging-port=9222")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )

    # En headless no usar experimental options que pueden causar problemas en CI
    if not headless:
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)

    service = Service(chromedriver_path) if chromedriver_path else Service()
    driver  = webdriver.Chrome(service=service, options=opts)

    if not headless:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })

    driver.implicitly_wait(10)
    logger.info(f"Chrome iniciado (headless={headless}, CI={_EN_CI})")
    return driver


def screenshot_base64(driver: webdriver.Chrome) -> str:
    """Captura screenshot y retorna en base64."""
    png = driver.get_screenshot_as_png()
    img = Image.open(BytesIO(png))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def analizar_pantalla_con_claude(driver: webdriver.Chrome, pregunta: str) -> str:
    """Análisis visual de la pantalla actual mediante Claude Vision."""
    if not config.USAR_COMPUTER_USE:
        return ""
    try:
        client  = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        img_b64 = screenshot_base64(driver)
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type":       "base64",
                            "media_type": "image/png",
                            "data":       img_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Eres un asistente que analiza capturas del portal educativo "
                            "Woot It — Alajuela Adventist Academy (Costa Rica). "
                            "Responde SOLO en español, de forma estructurada y completa. "
                            f"PREGUNTA: {pregunta}"
                        ),
                    },
                ],
            }],
        )
        return response.content[0].text
    except Exception as e:
        logger.warning(f"Claude Vision falló: {e}. Continuando con Selenium.")
        return ""


def wait_and_get(driver: webdriver.Chrome, url: str,
                  css_wait: str = "body", timeout: int = 20) -> bool:
    """Navega a URL y espera que el selector esté presente."""
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


def login(driver: webdriver.Chrome) -> bool:
    """Login en Woot It con retry (3 intentos)."""
    from selenium.common.exceptions import NoSuchElementException, TimeoutException

    for intento in range(1, 4):
        try:
            logger.info(f"Intento de login {intento}/3...")
            wait_and_get(driver, f"{config.BASE_URL}/login/")
            wait = WebDriverWait(driver, 15)

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

            logger.info("Clic en login. Esperando redirección...")
            time.sleep(5)

            # Cerrar modales si aparecen
            try:
                close_btns = driver.find_elements(
                    By.CSS_SELECTOR, ".close, .btn-close, [data-dismiss='modal']")
                for cb in close_btns:
                    if cb.is_displayed():
                        cb.click()
                        time.sleep(1)
            except Exception:
                pass

            # Verificar login exitoso
            WebDriverWait(driver, 25).until(
                lambda d: (d.find_elements(By.ID, SELECTOR_POST_LOGIN)
                           or "home" in d.current_url)
            )
            logger.info(f"Login exitoso. URL: {driver.current_url}")
            return True

        except TimeoutException:
            # Guardar screenshot para diagnóstico
            try:
                screenshot_path = f"/tmp/logs/error_login_{intento}.png"
                os.makedirs("/tmp/logs", exist_ok=True)
                driver.save_screenshot(screenshot_path)
                logger.warning(f"Login timeout. Screenshot: {screenshot_path}")
            except Exception:
                pass
        except (NoSuchElementException, Exception) as e:
            logger.warning(f"Error en login intento {intento}: {e}")
            time.sleep(3)

    return False


def cambiar_estudiante(driver: webdriver.Chrome,
                        nombre: str, grado_esperado: str) -> bool:
    """
    Cambia al perfil del estudiante.
    FIX: Navega a /home/ con recarga forzada + verificación post-cambio.
    """
    from selenium.common.exceptions import TimeoutException

    user_id = ESTUDIANTES_IDS.get(nombre)
    if not user_id:
        logger.error(f"ID no encontrado para: {nombre}")
        return False

    for intento in range(1, 4):
        try:
            logger.info(f"[cambiar_estudiante] Intento {intento}/3 — {nombre}")
            driver.get(f"{config.BASE_URL}/home/")
            wait = WebDriverWait(driver, 20)
            wait.until(EC.presence_of_element_located((By.ID, SELECTOR_BTN_MENU)))
            time.sleep(1.5)

            btn_menu = wait.until(EC.element_to_be_clickable((By.ID, SELECTOR_BTN_MENU)))
            btn_menu.click()
            time.sleep(1.5)

            wait.until(EC.visibility_of_element_located((By.ID, SELECTOR_SUBMENU)))

            avatar = wait.until(EC.element_to_be_clickable((By.ID, user_id)))
            avatar.click()
            logger.info(f"Clic en avatar {nombre} ({user_id})")

            time.sleep(3)

            # Verificar por header
            try:
                header = wait.until(
                    EC.presence_of_element_located((By.ID, SELECTOR_HEADER)))
                header_texto  = header.text.lower()
                grado_limpio  = grado_esperado.replace("°", "").strip().lower()
                nombre_primero = nombre.split()[0].lower()

                if nombre_primero in header_texto or grado_limpio in header_texto:
                    logger.info(f"Cambio a {nombre} confirmado via header.")
                    return True
                logger.warning(
                    f"Header no confirma {nombre} (visto: '{header_texto}'). "
                    f"Reintentando ({intento}/3)...")
            except TimeoutException:
                logger.warning(f"Header no encontrado al verificar cambio a {nombre}.")

            # Fallback: Computer Use
            if config.USAR_COMPUTER_USE:
                analisis = analizar_pantalla_con_claude(
                    driver,
                    f"La página muestra que el estudiante activo es {nombre} ({grado_esperado})? "
                    "Responde SI o NO."
                )
                if analisis and (
                    "sí" in analisis.lower() or "si" in analisis.lower()
                    or nombre.split()[0].lower() in analisis.lower()
                ):
                    logger.info(f"Cambio a {nombre} confirmado via Claude Vision.")
                    return True

            time.sleep(2)

        except Exception as e:
            logger.warning(f"cambiar_estudiante intento {intento} error: {e}")
            time.sleep(2)

    logger.error(f"Fallo definitivo: no se pudo cambiar a {nombre} tras 3 intentos.")
    return False
