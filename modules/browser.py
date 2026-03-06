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
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import config

logger = logging.getLogger(__name__)

# IDs reales del portal Woot It — Alajuela Adventist Academy
SELECTOR_POST_LOGIN = "button-show-menu"  # solo existe cuando hay sesión activa
SELECTOR_BTN_MENU   = "button-show-menu"  # abre el menú lateral
SELECTOR_SUBMENU    = "submenu-usuarios"  # contenedor de estudiantes
SELECTOR_HEADER     = "header"            # barra superior con nombre y grado

# Mapeo de estudiante → ID del avatar clicable en #submenu-usuarios
ESTUDIANTES_IDS = {
    "Carlos Emiliano": "user213",
    "Starling Andrés":  "user240",
}

# Detectar entorno CI (GitHub Actions define CI=true)
_EN_CI = os.environ.get("CI", "").lower() == "true"


def get_driver(headless: bool = True) -> webdriver.Chrome:
    """
    Crea y retorna un WebDriver de Chrome.

    - Usa Selenium Manager integrado (>= 4.6): sin webdriver-manager,
      sin bug de THIRD_PARTY_NOTICES.
    - En entornos CI (GitHub Actions) fuerza headless aunque el caller
      pida headless=False, porque no hay servidor de display disponible.
    """
    # En CI siempre headless, independientemente del argumento
    if _EN_CI:
        headless = True

    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    # Sin Service() → Selenium Manager resuelve el driver correcto
    driver = webdriver.Chrome(options=opts)
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


def wait_and_get(driver: webdriver.Chrome, url: str,
                 css_wait: str = "body", timeout: int = 20) -> bool:
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
    """Realiza login en Woot It usando IDs reales del portal. Reintenta hasta 3 veces."""
    from selenium.common.exceptions import NoSuchElementException, TimeoutException

    for intento in range(1, 4):
        try:
            wait_and_get(driver, f"{config.BASE_URL}/login/")
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            campo_user = driver.find_element(By.ID, "username")
            campo_pass = driver.find_element(By.ID, "password")
            btn_login  = driver.find_element(By.ID, "loginBtn")

            campo_user.clear()
            campo_user.send_keys(config.WOOTIT_USER)
            campo_pass.clear()
            campo_pass.send_keys(config.WOOTIT_PASS)
            btn_login.click()

            # Confirmar sesión activa: id="button-show-menu" solo existe logueado
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, SELECTOR_POST_LOGIN))
            )
            logger.info("Login exitoso.")
            return True
        except (NoSuchElementException, TimeoutException) as e:
            logger.warning(f"Login intento {intento} falló: {e}")
            time.sleep(3)
        except Exception as e:
            logger.warning(f"Login intento {intento} falló (error general): {e}")
            time.sleep(3)

    return False


def cambiar_estudiante(driver: webdriver.Chrome, nombre: str, grado_esperado: str) -> bool:
    """
    Cambia al estudiante usando su ID de avatar real en #submenu-usuarios.
    Carlos Emiliano → id="user213"
    Starling Andrés  → id="user240"
    """
    user_id = ESTUDIANTES_IDS.get(nombre)
    if not user_id:
        logger.error(f"No se encontró ID de usuario para: {nombre}")
        return False

    for intento in range(1, 3):
        try:
            wait_and_get(driver, f"{config.BASE_URL}/home/")

            # Abrir menú lateral
            btn_menu = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, SELECTOR_BTN_MENU))
            )
            btn_menu.click()
            time.sleep(1)

            # Esperar que el submenú esté visible
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, SELECTOR_SUBMENU))
            )

            # Clic directo en el avatar del estudiante por su ID real
            avatar = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, user_id))
            )
            avatar.click()
            time.sleep(2)

            # Confirmar grado en el header
            header = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, SELECTOR_HEADER))
            )
            header_texto = header.text.lower()
            grado_limpio = grado_esperado.replace("°", "").strip().lower()

            if grado_limpio in header_texto or grado_esperado.lower() in header_texto:
                logger.info(f"Cambio a {nombre} confirmado. Header: {header.text.strip()}")
                return True

            logger.warning(f"Header no confirmó grado para {nombre}. Texto: {header.text.strip()}")

            # Fallback Computer Use
            if config.USAR_COMPUTER_USE:
                analisis = analizar_pantalla_con_claude(
                    driver,
                    f"¿La página muestra que el estudiante activo es {nombre} ({grado_esperado})?"
                )
                if "sí" in analisis.lower() or nombre.split()[0].lower() in analisis.lower():
                    logger.info(f"Cambio a {nombre} confirmado via Computer Use.")
                    return True

            # Último fallback: asumir éxito si el clic no generó error
            logger.warning(f"Asumiendo cambio exitoso a {nombre} (no se pudo confirmar por header).")
            return True

        except Exception as e:
            logger.warning(f"Cambio de estudiante intento {intento} falló: {e}")
            time.sleep(2)

    return False
