"""
Módulo de navegador: combina Selenium (navegación estructurada)
y Claude Computer Use (análisis visual) para máxima cobertura.
"""
import base64
import logging
import os
import time
from io import BytesIO
import anthropic
from PIL import Image
import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import config

logger = logging.getLogger(__name__)

# IDs reales del portal Woot It — Alajuela Adventist Academy
SELECTOR_POST_LOGIN = "button-show-menu"
SELECTOR_BTN_MENU = "button-show-menu"
SELECTOR_SUBMENU = "submenu-usuarios"
SELECTOR_HEADER = "header"

# Mapeo de estudiante → ID del avatar clicable en #submenu-usuarios
ESTUDIANTES_IDS = {
    "Carlos Emiliano": "user213",
    "Starling Andrés": "user240",
}

_EN_CI = os.environ.get("CI", "").lower() == "true"


def get_driver(headless: bool = True) -> webdriver.Chrome:
    """
    Crea y retorna un WebDriver de Chrome con técnicas anti-detección reforzadas.
    """
    if _EN_CI:
        headless = True
    chromedriver_autoinstaller.install()  # BUG [24] CORREGIDO: chromedriver compatible con Chrome instalado
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-notifications")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """
    })
    driver.implicitly_wait(10)
    return driver


def screenshot_base64(driver: webdriver.Chrome) -> str:
    """Captura screenshot y retorna en base64 para Computer Use."""
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
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
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
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Eres un asistente que analiza capturas de pantalla del portal educativo "
                            "Woot It — Alajuela Adventist Academy (Costa Rica). "
                            "Responde SOLO en español, de forma estructurada y completa. "
                            "Transcribe tablas, listas y mensajes íntegros. "
                            f"PREGUNTA: {pregunta}"
                        ),
                    },
                ],
            }],
        )
        return response.content[0].text
    except Exception as e:
        logger.warning(f"Computer Use falló: {e}. Continuando con Selenium.")
        return ""


def wait_and_get(driver: webdriver.Chrome, url: str, css_wait: str = "body", timeout: int = 20) -> bool:
    """Navega a URL y espera que el elemento indicado esté presente."""
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
    """Realiza login en Woot It. Incluye guardado de capturas en caso de error."""
    from selenium.common.exceptions import NoSuchElementException, TimeoutException
    for intento in range(1, 4):
        try:
            logger.info(f"Intento de login {intento}/3...")
            wait_and_get(driver, f"{config.BASE_URL}/login/")
            wait = WebDriverWait(driver, 15)
            campo_user = wait.until(EC.element_to_be_clickable((By.ID, "username")))
            campo_pass = driver.find_element(By.ID, "password")
            btn_login = driver.find_element(By.ID, "loginBtn")
            campo_user.clear()
            campo_user.send_keys(config.WOOTIT_USER)
            time.sleep(0.5)
            campo_pass.clear()
            campo_pass.send_keys(config.WOOTIT_PASS)
            time.sleep(0.5)
            btn_login.click()
            logger.info("Clic en botón de login realizado. Esperando redirección...")
            time.sleep(5)
            try:
                try:
                    close_btns = driver.find_elements(By.CSS_SELECTOR, ".close, .btn-close, [data-dismiss='modal'], .modal-footer button")
                    for cb in close_btns:
                        if cb.is_displayed():
                            logger.info("Modal detectado tras login, intentando cerrar...")
                            cb.click()
                            time.sleep(1)
                except:
                    pass
                WebDriverWait(driver, 25).until(
                    lambda d: d.find_elements(By.ID, SELECTOR_POST_LOGIN) or "home" in d.current_url
                )
                logger.info(f"Login exitoso. URL actual: {driver.current_url}")
                return True
            except TimeoutException:
                try:
                    error_msg = driver.find_element(By.CSS_SELECTOR, ".alert-danger, .error-message, .error").text
                    logger.warning(f"Error de login detectado en portal: {error_msg}")
                except:
                    pass
                filename = f"error_login_intento_{intento}.png"
                if not os.path.exists(config.DIR_LOGS):
                    os.makedirs(config.DIR_LOGS)
                driver.save_screenshot(os.path.join(config.DIR_LOGS, filename))
                logger.warning(f"Login no confirmado. Captura guardada como {filename}")
        except (NoSuchElementException, TimeoutException) as e:
            logger.warning(f"Error de elementos en login: {e}")
            time.sleep(3)
        except Exception as e:
            logger.warning(f"Error general en login: {e}")
            time.sleep(3)
    return False


def cambiar_estudiante(driver: webdriver.Chrome, nombre: str, grado_esperado: str) -> bool:
    """
    Cambia al perfil del estudiante indicado.

    FIX: Navega a /home/ forzando recarga completa para limpiar el estado del
    perfil anterior. Verifica el header hasta 3 veces antes de reportar error.
    """
    from selenium.common.exceptions import TimeoutException

    user_id = ESTUDIANTES_IDS.get(nombre)
    if not user_id:
        logger.error(f"No se encontró ID de usuario para: {nombre}")
        return False

    for intento in range(1, 4):
        try:
            # PASO 1: Recarga forzada de /home/ para limpiar perfil anterior
            logger.info(f"[cambiar_estudiante] Intento {intento}/3 — recargando /home/")
            driver.get(f"{config.BASE_URL}/home/")
            wait = WebDriverWait(driver, 20)
            wait.until(EC.presence_of_element_located((By.ID, SELECTOR_BTN_MENU)))
            time.sleep(1.5)

            # PASO 2: Abrir menú lateral
            btn_menu = wait.until(EC.element_to_be_clickable((By.ID, SELECTOR_BTN_MENU)))
            btn_menu.click()
            time.sleep(1.5)

            # PASO 3: Esperar submenú de estudiantes visible
            wait.until(EC.visibility_of_element_located((By.ID, SELECTOR_SUBMENU)))

            # PASO 4: Clic en el avatar del estudiante objetivo
            avatar = wait.until(EC.element_to_be_clickable((By.ID, user_id)))
            avatar.click()
            logger.info(f"Clic en avatar de {nombre} ({user_id}) realizado.")

            # PASO 5: Esperar que el portal aplique el cambio (puede redirigir)
            time.sleep(3)
            try:
                wait.until(
                    lambda d: d.find_elements(By.ID, SELECTOR_BTN_MENU)
                    and SELECTOR_BTN_MENU in d.page_source
                )
            except TimeoutException:
                logger.warning(f"Timeout esperando recarga post-cambio a {nombre}.")

            # PASO 6: Verificar header para confirmar perfil activo
            try:
                header = wait.until(EC.presence_of_element_located((By.ID, SELECTOR_HEADER)))
                header_texto = header.text.lower()
                grado_limpio = grado_esperado.replace("°", "").strip().lower()
                nombre_primero = nombre.split()[0].lower()

                if nombre_primero in header_texto or grado_limpio in header_texto:
                    logger.info(f"Cambio a {nombre} confirmado. Header: '{header.text.strip()}'")
                    return True
                else:
                    logger.warning(
                        f"Header no confirma {nombre} (visto: '{header_texto}'). "
                        f"Reintentando ({intento}/3)..."
                    )
            except TimeoutException:
                logger.warning(f"Header no encontrado al verificar cambio a {nombre}.")

            # FALLBACK: Computer Use
            if config.USAR_COMPUTER_USE:
                analisis = analizar_pantalla_con_claude(
                    driver,
                    f"¿La página muestra que el estudiante activo es {nombre} ({grado_esperado})? "
                    "Responde SÍ o NO e indica el texto exacto del header visible."
                )
                if "sí" in analisis.lower() or nombre.split()[0].lower() in analisis.lower():
                    logger.info(f"Cambio a {nombre} confirmado via Computer Use.")
                    return True
                logger.warning(f"Computer Use no confirmó cambio: {analisis[:200]}")

            time.sleep(2)

        except Exception as e:
            logger.warning(f"Cambio de estudiante intento {intento}/3 excepción: {e}")
            time.sleep(2)

    logger.error(f"Fallo definitivo: no se pudo cambiar al perfil de {nombre} tras 3 intentos.")
    return False
