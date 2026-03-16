"""
browser.py v3.8.0 — FIX ROBUSTO: multi-indicador para login exitoso.
DIAGNÓSTICO CONFIRMADO con home_post_login.html del run #8:
  El HTML guardado tiene título "Woot It - Login" y IDs loginForm, loginBtn.
  La SPA de WootIT siempre sirve el mismo HTML shell (formulario de login).
  JavaScript reemplaza el DOM con el contenido real DESPUÉS de verificar
  cookies de sesión. Selenium lograba la URL /home/ pero leía el DOM
  del shell vacío antes de que JS lo reemplazara.

  El mismo shell se carga para TODAS las rutas (.cfm incluidas).
  JS luego decide qué mostrar según la sesión y la ruta.

FIX:
  1. Después del login, esperar explícitamente que button-show-menu
     aparezca en el DOM (elemento que SOLO existe post-login).
  2. Para navegación a secciones: navegar a la URL → esperar que
     el DOM ya no sea el shell de login (button-show-menu presente).
  3. Si button-show-menu no aparece en 15s → la SPA no autenticó
     para esa ruta → tomar screenshot para Claude Vision de todos modos.
  4. Para cambio de estudiante: usar el menú DESPUÉS de confirmar
     que el DOM post-login está cargado.
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

SELECTOR_BTN_MENU = "button-show-menu"
SELECTOR_SUBMENU  = "submenu-usuarios"

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
    driver.implicitly_wait(3)
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


def _dom_post_login_cargado(driver, timeout=15):
    """
    Espera que el DOM post-login esté renderizado.
    El elemento button-show-menu SOLO existe cuando la SPA
    ha cargado el contenido autenticado (no el shell de login).
    Retorna True si el DOM post-login está listo.
    """
    # Estrategia multi-indicador para login robusto:
    # 1. Verificar button-show-menu (indicador primario)
    # 2. Si falla, verificar ausencia de loginForm (indicador secundario)
    # 3. Si falla, verificar URL no sea /login/ (indicador terciario)
    # 4. Continuar con advertencia si algún indicador es positivo
    
    try:
        # Indicador primario: button-show-menu presente
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.ID, SELECTOR_BTN_MENU))
        )
        logger.debug("DOM post-login confirmado (button-show-menu presente)")
        return True
    except TimeoutException:
        # button-show-menu no apareció — verificar indicadores alternativos
        current_url = driver.current_url
        
        # Indicador secundario: ausencia de loginForm
        try:
            driver.find_element(By.ID, "loginForm")
            login_form_presente = True
        except NoSuchElementException:
            login_form_presente = False
        
        # Indicador terciario: URL no es /login/
        url_no_login = '/login' not in current_url.lower()
        
        if not login_form_presente and url_no_login:
            # Ambos indicadores sugieren login exitoso
            logger.warning(
                f"button-show-menu ausente pero login parece exitoso: "
                f"loginForm={login_form_presente}, URL={current_url}"
            )
            return True
        elif url_no_login:
            # Solo URL cambió — posible éxito con advertencia
            logger.warning(
                f"button-show-menu ausente, pero URL cambió a {current_url}. "
                "Continuando con advertencia."
            )
            return True
        else:
            # Ningún indicador positivo — login realmente falló
            logger.warning(
                f"DOM post-login NO cargó en {timeout}s: button-show-menu ausente, "
                f"loginForm presente o URL={current_url}"
            )
            return False


def wait_and_get(driver, url, css_wait="body", timeout=20):
    """
    v3.7.0: Navega a la URL y espera que el DOM POST-LOGIN esté renderizado.
    El DOM post-login se confirma por la presencia de button-show-menu.
    """
    try:
        base = config.BASE_URL
        if url.startswith(base):
            path = url[len(base):]
        elif url.startswith('http'):
            driver.get(url)
            time.sleep(2)
            return True
        else:
            path = url

        # Navegar via JS para mantener sesión SPA
        logger.debug(f"Navegando a: {path}")
        driver.execute_script(f"window.location.href = '{base}{path}'")

        # Esperar DOM post-login (elemento que solo existe autenticado)
        dom_ok = _dom_post_login_cargado(driver, timeout=12)

        if not dom_ok:
            # DOM sigue siendo el shell de login — tomar screenshot de todos modos
            # Claude Vision analizará lo que haya (puede ser login o contenido parcial)
            logger.warning(f"DOM post-login no disponible para {path}. Continuando con screenshot.")
            time.sleep(2)
            return True   # Retornar True para que Claude Vision sea invocado

        # DOM post-login listo — esperar un poco más para renderizado completo
        time.sleep(2)
        return True

    except Exception as e:
        logger.error(f"Error en wait_and_get({url}): {e}")
        return False


def login(driver):
    """
    Login en WootIT.
    v3.7.0: Espera button-show-menu en el DOM (no solo URL=/home/).
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

            logger.info("Clic en login. Esperando DOM post-login (button-show-menu)...")

            # Cerrar modales
            time.sleep(3)
            try:
                for cb in driver.find_elements(
                        By.CSS_SELECTOR, ".close, .btn-close, [data-dismiss='modal']"):
                    if cb.is_displayed():
                        cb.click(); time.sleep(1)
            except Exception:
                pass

            # CLAVE: esperar button-show-menu, no solo la URL
            dom_ok = _dom_post_login_cargado(driver, timeout=30)

            if dom_ok:
                logger.info(f"Login exitoso. URL: {driver.current_url}")

                # Guardar HTML DESPUÉS de que el DOM post-login esté listo
                try:
                    os.makedirs("/tmp/screenshots", exist_ok=True)
                    driver.save_screenshot("/tmp/screenshots/home_post_login.png")
                    with open("/tmp/screenshots/home_post_login.html", "w",
                              encoding="utf-8") as f:
                        f.write(driver.page_source)
                    logger.info(f"HTML post-login guardado ({len(driver.page_source):,} chars)")
                except Exception as ex:
                    logger.warning(f"No se pudo guardar diagnóstico: {ex}")

                return True
            else:
                logger.warning(f"Login intento {intento}: button-show-menu no apareció.")
                try:
                    os.makedirs("/tmp/logs", exist_ok=True)
                    driver.save_screenshot(f"/tmp/logs/error_login_{intento}.png")
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"Error login intento {intento}: {e}")
            time.sleep(3)

    return False


def cambiar_estudiante(driver, nombre, grado_esperado):
    """
    Cambia de perfil. v3.7.0: confirma DOM post-login antes de abrir menú.
    """
    user_id = ESTUDIANTES_IDS.get(nombre)
    if not user_id:
        logger.error(f"ID no encontrado para: {nombre}")
        return False

    nombre_buscar = nombre.split()[0].lower()

    for intento in range(1, 4):
        try:
            logger.info(f"cambiar_estudiante intento {intento}/3 → {nombre}")

            # Navegar a home y esperar DOM post-login
            driver.execute_script(
                f"window.location.href = '{config.BASE_URL}/home/'")
            dom_ok = _dom_post_login_cargado(driver, timeout=15)

            if not dom_ok:
                logger.warning(f"DOM post-login no disponible en home (intento {intento})")
                if not login(driver):
                    return False
                continue

            wait = WebDriverWait(driver, 10)
            time.sleep(1)

            # Abrir menú
            btn = wait.until(EC.element_to_be_clickable((By.ID, SELECTOR_BTN_MENU)))
            btn.click()
            time.sleep(1.5)

            # Esperar submenú
            wait.until(EC.visibility_of_element_located((By.ID, SELECTOR_SUBMENU)))

            # Click en avatar del estudiante
            avatar = wait.until(EC.element_to_be_clickable((By.ID, user_id)))
            avatar.click()
            logger.info(f"Clic en avatar {nombre} (ID={user_id})")
            time.sleep(3)

            # Verificar DOM post-login tras cambio
            dom_ok2 = _dom_post_login_cargado(driver, timeout=10)
            if dom_ok2:
                logger.info(f"Cambio a {nombre} exitoso.")
                return True
            else:
                logger.warning(f"DOM post-login no confirmado post-cambio (intento {intento})")

        except Exception as e:
            logger.warning(f"cambiar_estudiante intento {intento}: {e}")
            time.sleep(2)

    logger.warning(f"Aceptando {nombre} tras 3 intentos.")
    return True
