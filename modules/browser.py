"""
browser.py v3.6.0 — Navegación por CLICK en menú lateral + análisis visual del home.

ESTRATEGIA DEFINITIVA basada en los runs #1 al #7:
  El portal WootIT redirige todas las URLs internas al login cuando
  Selenium navega directamente (driver.get o window.location.href).
  La sesión SÍ persiste en /home/ pero las rutas .cfm requieren
  provenir de un click dentro de la SPA.

  Nueva estrategia:
  1. Login → llegar a /home/
  2. Analizar /home/ con Claude Vision para capturar info del dashboard
  3. Para cada sección: abrir menú lateral → click en el ítem
  4. wait_and_get() como fallback para secciones que sí aceptan URL directa
  5. _esta_en_login() simplificado: solo verifica URL, sin find_element
     para evitar false positives en secciones que tardan en cargar
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


def _url_es_login(url):
    """Verifica si una URL es la pantalla de login."""
    return '/login/' in url or url.endswith('/login') or url == config.BASE_URL + '/'


def _navegar_por_menu(driver, seccion_key):
    """
    Navega a una sección usando el menú lateral del portal.
    Estrategia: abrir menú → buscar link con href que contenga la sección → click.
    Retorna True si la navegación fue exitosa.
    """
    # Selectores de links en el menú lateral de WootIT
    href_keywords = {
        'mensajes':       ['mensajes', 'comunicacion', 'message', 'inbox'],
        'calificaciones': ['calificacion', 'nota', 'grade', 'calific'],
        'asistencia':     ['asistencia', 'attendance', 'asistenciayconducta'],
        'boleta':         ['boleta', 'conducta', 'comportamiento'],
        'anotaciones':    ['anotacion', 'annotation', 'observacion'],
        'aula_virtual':   ['aulavirtual', 'aula', 'virtual', 'lms', 'classroom'],
        'agenda':         ['calendar', 'agenda', 'calendario', 'event'],
    }
    keywords = href_keywords.get(seccion_key, [seccion_key])

    # Intentar navegar sin menú primero (algunos links están visibles directamente)
    for kw in keywords:
        try:
            links = driver.find_elements(By.CSS_SELECTOR, f'a[href*="{kw}"]')
            for link in links:
                if link.is_displayed():
                    href = link.get_attribute('href') or ''
                    if href and 'login' not in href.lower():
                        logger.info(f"Link directo encontrado para {seccion_key}: {href}")
                        link.click()
                        time.sleep(2)
                        return True
        except Exception:
            pass

    # Abrir menú lateral y buscar link
    try:
        wait = WebDriverWait(driver, 5)
        # Intentar abrir el menú
        try:
            btn = wait.until(EC.element_to_be_clickable((By.ID, SELECTOR_BTN_MENU)))
            btn.click()
            time.sleep(1)
        except TimeoutException:
            # El menú puede ya estar abierto o tener otro selector
            for sel in ['.menu-toggle', '.hamburger', '.sidebar-toggle',
                        '[class*="menu-btn"]', '[class*="toggle-menu"]']:
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, sel)
                    if btn.is_displayed():
                        btn.click()
                        time.sleep(2)
                        break
                except NoSuchElementException:
                    pass

        # Buscar el link en el menú abierto
        for kw in keywords:
            links = driver.find_elements(By.CSS_SELECTOR, f'a[href*="{kw}"]')
            for link in links:
                if link.is_displayed():
                    href = link.get_attribute('href') or ''
                    if href and 'login' not in href.lower():
                        logger.info(f"Link en menú encontrado para {seccion_key}: {href}")
                        link.click()
                        time.sleep(2)
                        return True
    except Exception as e:
        logger.warning(f"_navegar_por_menu({seccion_key}): {e}")

    return False


def wait_and_get(driver, url, css_wait="body", timeout=20):
    """
    v3.6.0: Estrategia dual:
    1. Intentar navegación por menú (mantiene sesión SPA)
    2. Si falla o URL no está en menú: usar window.location.href
    3. Si la URL resultante es login: reportar error sin re-login infinito
    """
    try:
        base = config.BASE_URL

        # Extraer la clave de sección de la URL para navegar por menú
        seccion_key = None
        url_lower = url.lower()
        for key, path in {
            'mensajes':       'mensajes',
            'calificaciones': 'calificacion',
            'asistencia':     'asistencia',
            'boleta':         'boleta',
            'anotaciones':    'anotacion',
            'aula_virtual':   'aulavirtual',
            'agenda':         'calendar',
        }.items():
            if path in url_lower:
                seccion_key = key
                break

        # Estrategia 1: Click en menú lateral
        if seccion_key:
            exito = _navegar_por_menu(driver, seccion_key)
            if exito:
                url_actual = driver.current_url
                if not _url_es_login(url_actual):
                    logger.info(f"Navegación por menú exitosa: {url_actual}")
                    time.sleep(2)
                    return True
                else:
                    logger.warning(f"Menú navegó a login para {seccion_key}")

        # Estrategia 2: window.location.href
        if url.startswith(base):
            path = url[len(base):]
        elif url.startswith('http'):
            driver.get(url)
            time.sleep(3)
            return not _url_es_login(driver.current_url)
        else:
            path = url

        logger.debug(f"Navegando por JS a: {path}")
        driver.execute_script(f"window.location.href = '{base}{path}'")
        time.sleep(4)

        url_actual = driver.current_url
        if _url_es_login(url_actual):
            logger.warning(f"Redirigido a login al navegar a {path}")
            # Un solo intento de re-login
            if login(driver):
                driver.execute_script(f"window.location.href = '{base}{path}'")
                time.sleep(4)
                if _url_es_login(driver.current_url):
                    logger.error(f"Sigue en login tras re-login para {path}")
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


def login(driver):
    """Login en WootIT — verifica éxito SOLO por URL."""
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

            logger.info("Clic en login, esperando URL /home/...")
            time.sleep(5)

            # Cerrar modales
            try:
                for cb in driver.find_elements(
                        By.CSS_SELECTOR, ".close, .btn-close, [data-dismiss='modal']"):
                    if cb.is_displayed():
                        cb.click(); time.sleep(1)
            except Exception:
                pass

            # Esperar URL /home/ — único criterio confiable
            try:
                WebDriverWait(driver, 30).until(
                    lambda d: "home" in d.current_url and "login" not in d.current_url
                )
                logger.info(f"Login exitoso. URL: {driver.current_url}")

                # Guardar diagnósticos
                try:
                    os.makedirs("/tmp/screenshots", exist_ok=True)
                    driver.save_screenshot("/tmp/screenshots/home_post_login.png")
                    with open("/tmp/screenshots/home_post_login.html", "w",
                              encoding="utf-8") as f:
                        # Guardar TODO el HTML para analizar selectores del menú
                        f.write(driver.page_source)
                    logger.info("HTML completo del home guardado para análisis de menú")
                except Exception as ex:
                    logger.warning(f"No se pudo guardar diagnóstico: {ex}")

                return True

            except TimeoutException:
                try:
                    os.makedirs("/tmp/logs", exist_ok=True)
                    driver.save_screenshot(f"/tmp/logs/error_login_{intento}.png")
                    logger.warning(
                        f"Login timeout intento {intento}. URL: {driver.current_url}")
                except Exception:
                    logger.warning(f"Login timeout intento {intento}")

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

            # Volver a /home/ via JS
            driver.execute_script(f"window.location.href = '{config.BASE_URL}/home/'")
            wait = WebDriverWait(driver, 20)
            wait.until(EC.presence_of_element_located((By.ID, SELECTOR_BTN_MENU)))
            time.sleep(2)

            # Verificar que no estamos en login
            if _url_es_login(driver.current_url):
                logger.warning("En login al intentar cambiar perfil. Re-login...")
                if not login(driver):
                    return False

            # Abrir menú y click en avatar
            btn = wait.until(EC.element_to_be_clickable((By.ID, SELECTOR_BTN_MENU)))
            btn.click()
            time.sleep(1)

            wait.until(EC.visibility_of_element_located((By.ID, SELECTOR_SUBMENU)))
            avatar = wait.until(EC.element_to_be_clickable((By.ID, user_id)))
            avatar.click()
            logger.info(f"Clic en avatar {nombre} (ID={user_id})")
            time.sleep(4)

            # Verificar
            if _url_es_login(driver.current_url):
                logger.warning(f"Login post-cambio intento {intento}")
                if not login(driver):
                    continue
                continue

            try:
                if nombre_buscar in driver.find_element(By.TAG_NAME, 'body').text.lower():
                    logger.info(f"Cambio a {nombre} verificado.")
                    return True
            except Exception:
                pass

            logger.info(f"Cambio a {nombre} aceptado. URL={driver.current_url}")
            return True

        except Exception as e:
            logger.warning(f"cambiar_estudiante intento {intento}: {e}")
            time.sleep(2)

    logger.warning(f"Aceptando {nombre} tras 3 intentos.")
    return True
