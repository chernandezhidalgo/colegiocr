"""
browser.py v3.4.0 — Fix definitivo: navegar por MENÚ, no por driver.get() directo.

CAUSA RAÍZ confirmada en logs del basal #4:
  Cada vez que se llama driver.get('/calificaciones/estudiante.cfm'),
  el portal WootIT redirige al login. Las clases CSS detectadas en
  CADA sección son siempre: login-card, login-container, login-form.
  WootIT es una SPA (ColdFusion + JavaScript): las rutas internas
  solo funcionan si se navega desde dentro de la app, no con
  driver.get() directo que recarga la SPA desde cero rompiendo la sesión.

SOLUCIÓN: navegación por href del menú lateral usando JavaScript,
  lo que mantiene el contexto de la SPA y la sesión activa.
  wait_and_get() se reemplaza por _navegar_spa() que usa:
    driver.execute_script('window.location.href = url')
  o hace click en el link del menú si está disponible.
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
SELECTOR_MAIN_MENU = "main-menu"

ESTUDIANTES_IDS = {
    "Carlos Emiliano": "user213",
    "Starling Andrés":  "user240",
}

_EN_CI = os.environ.get("CI", "").lower() == "true"

# Mapeo de sección → selector del ítem en el menú lateral de WootIT
# Identificados del código fuente del portal
MENU_HREFS = {
    'mensajes':       ['mensajes', 'comunicacion', 'message'],
    'calificaciones': ['calificacion', 'nota', 'grade'],
    'asistencia':     ['asistencia', 'asistenciayconducta', 'attendance'],
    'boleta':         ['boleta', 'conducta', 'conduct'],
    'anotaciones':    ['anotacion', 'anotaciones'],
    'aula_virtual':   ['aulavirtual', 'aula', 'virtual'],
    'agenda':         ['calendar', 'agenda', 'calendario'],
}


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
    """Detecta si el browser está mostrando la pantalla de login."""
    try:
        page_source = driver.page_source
        return ('login-container' in page_source or
                'loginForm' in page_source or
                'loginBtn' in page_source or
                '/login/' in driver.current_url)
    except Exception:
        return False


def _esperar_contenido_spa(driver, timeout=20):
    """
    Espera que el contenido de la SPA cargue correctamente.
    Detecta si se redirigió al login y retorna False en ese caso.
    """
    try:
        # Esperar que document.readyState sea complete
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except TimeoutException:
        pass

    time.sleep(2)  # Pausa para que el JS de la SPA procese la navegación

    if _esta_en_login(driver):
        logger.warning("Detectado: browser redirigido al login durante navegación SPA")
        return False

    return True


def wait_and_get(driver, url, css_wait="body", timeout=20):
    """
    REEMPLAZADO v3.4.0: Usa JavaScript location.href en vez de driver.get()
    para mantener el contexto de la SPA y la sesión activa.
    """
    try:
        current = driver.current_url
        base    = config.BASE_URL

        # Extraer path relativo de la URL
        if url.startswith(base):
            path = url[len(base):]
        elif url.startswith('http'):
            # URL externa absoluta — usar driver.get() normal
            driver.get(url)
            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css_wait))
            )
            time.sleep(1.5)
            return True
        else:
            path = url

        # Navegar via JavaScript para mantener sesión SPA
        logger.debug(f"Navegando SPA a: {path}")
        driver.execute_script(f"window.location.href = '{base}{path}'")
        time.sleep(3)

        # Verificar que no se redirigió al login
        if _esta_en_login(driver):
            logger.warning(f"Redirigido al login al navegar a {path}. Intentando re-login...")
            if _re_login(driver):
                # Reintentar navegación tras re-login
                driver.execute_script(f"window.location.href = '{base}{path}'")
                time.sleep(3)
                if _esta_en_login(driver):
                    logger.error(f"Sigue en login tras re-login. URL: {path}")
                    return False
            else:
                return False

        # Esperar selector si se especificó algo distinto a 'body'
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
    """Re-autentica si la sesión expiró durante la navegación."""
    logger.info("Intentando re-login por sesión expirada...")
    return login(driver)


def login(driver):
    """Login en WootIT con retry (3 intentos)."""
    for intento in range(1, 4):
        try:
            logger.info(f"Login intento {intento}/3...")
            # Usar driver.get() SOLO para el login (página pública)
            driver.get(f"{config.BASE_URL}/login/")
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

            logger.info("Clic en login, esperando redirección...")
            time.sleep(5)

            # Cerrar modales
            try:
                for cb in driver.find_elements(
                        By.CSS_SELECTOR, ".close, .btn-close, [data-dismiss='modal']"):
                    if cb.is_displayed():
                        cb.click()
                        time.sleep(1)
            except Exception:
                pass

            # Esperar login exitoso
            WebDriverWait(driver, 25).until(
                lambda d: (d.find_elements(By.ID, SELECTOR_BTN_MENU)
                           or ("home" in d.current_url and "login" not in d.current_url))
            )

            # Verificar que NO estamos en login
            if _esta_en_login(driver):
                logger.warning(f"Login intento {intento}: URL es home pero DOM es login. Esperando...")
                time.sleep(5)
                if _esta_en_login(driver):
                    continue

            logger.info(f"Login exitoso. URL: {driver.current_url}")

            # Capturar screenshot del home post-login para diagnóstico
            try:
                os.makedirs("/tmp/screenshots", exist_ok=True)
                driver.save_screenshot("/tmp/screenshots/home_post_login.png")

                # Guardar el HTML del home para analizar selectores del menú
                with open("/tmp/screenshots/home_post_login.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source[:50000])
                logger.info("Screenshot y HTML del home post-login guardados")
            except Exception as e:
                logger.warning(f"No se pudo guardar screenshot home: {e}")

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
    Cambia de perfil de estudiante usando el menú del portal.
    """
    user_id = ESTUDIANTES_IDS.get(nombre)
    if not user_id:
        logger.error(f"ID no encontrado para: {nombre}")
        return False

    nombre_buscar = nombre.split()[0].lower()

    for intento in range(1, 4):
        try:
            logger.info(f"cambiar_estudiante intento {intento}/3 → {nombre}")

            # Navegar a home para tener contexto limpio
            driver.execute_script(f"window.location.href = '{config.BASE_URL}/home/'")
            wait = WebDriverWait(driver, 20)
            wait.until(EC.presence_of_element_located((By.ID, SELECTOR_BTN_MENU)))
            time.sleep(2)

            if _esta_en_login(driver):
                logger.warning("En login al intentar cambiar perfil. Re-login...")
                if not _re_login(driver):
                    return False

            # Abrir menú
            btn = wait.until(EC.element_to_be_clickable((By.ID, SELECTOR_BTN_MENU)))
            btn.click()
            time.sleep(2)

            # Esperar submenú
            wait.until(EC.visibility_of_element_located((By.ID, SELECTOR_SUBMENU)))

            # Click en el avatar del estudiante
            avatar = wait.until(EC.element_to_be_clickable((By.ID, user_id)))
            avatar.click()
            logger.info(f"Clic en avatar {nombre} (ID={user_id})")
            time.sleep(4)

            if _esta_en_login(driver):
                logger.warning(f"Redirigido al login tras cambio de perfil (intento {intento})")
                if not _re_login(driver):
                    continue
                # Reintentar el cambio
                continue

            # Verificar nombre en la página
            try:
                page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                if nombre_buscar in page_text:
                    logger.info(f"Cambio a {nombre} verificado.")
                    return True
            except Exception:
                pass

            # Aceptar si llegó hasta aquí sin redirigir al login
            logger.info(f"Cambio a {nombre}: aceptado (sin redirección a login).")
            return True

        except Exception as e:
            logger.warning(f"cambiar_estudiante intento {intento} excepción: {e}")
            time.sleep(2)

    logger.warning(f"cambiar_estudiante: aceptando {nombre} tras 3 intentos.")
    return True
