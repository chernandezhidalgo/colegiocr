"""
wootit.py v3.3.0 — Fix SPA: esperar contenido real, no solo body.

CAUSA RAÍZ de datos vacíos:
  WootIT es una Single Page Application (SPA). Cuando Selenium navega a
  una sección, el <body> aparece en ~1s pero el contenido real (tablas,
  eventos, notas) se carga vía JavaScript/AJAX en los siguientes 3-8s.
  El código anterior usaba wait_and_get(url, 'body') y leía el DOM vacío.

SOLUCIÓN:
  Cada sección ahora espera su propio selector de contenido específico
  antes de leer el DOM. Si ese selector no aparece en 15s → fallback
  con tiempo de espera extendido (document.readyState + pausa adicional).
"""
import json
import logging
import re
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

import config
from modules.attachments import procesar_adjunto
from modules.browser import analizar_pantalla_con_claude, wait_and_get

TZ_CR  = ZoneInfo('America/Costa_Rica')
logger = logging.getLogger(__name__)

SECCIONES = {
    'mensajes':       '/comunicacion/mensajes/recibidos.cfm',
    'calificaciones': '/calificaciones/estudiante.cfm',
    'asistencia':     '/asistenciayconductaEst/index.cfm?sec=asistencia',
    'boleta':         '/asistenciayconductaEst/index.cfm?sec=boletas',
    'anotaciones':    '/asistenciayconductaEst/index.cfm?sec=anotaciones',
    'aula_virtual':   '/aulavirtual/',
    'agenda':         '/v3/calendar/home/index.cfm',
}

# Selectores que indican que el contenido dinámico YA cargó en cada sección
SELECTORES_CONTENIDO = {
    'mensajes':       ['table', '.mensaje-fila', '.message-row', 'tr.mensaje',
                       '#mensajes-container', '.inbox', '[class*="mensaje"]'],
    'calificaciones': ['table', '.calificacion-row', '.nota-row',
                       '#calificaciones-container', '[class*="calificacion"]',
                       '[class*="grade"]', '.materias'],
    'asistencia':     ['table', '.asistencia-row', '#asistencia-container',
                       '[class*="asistencia"]', '[class*="attendance"]', '.porcentaje'],
    'boleta':         ['table', '.boleta', '#boleta-container', '[class*="boleta"]',
                       '[class*="conducta"]'],
    'anotaciones':    ['table', '.anotacion', '#anotaciones-container',
                       '[class*="anotacion"]'],
    'aula_virtual':   ['.tarea-item', '.assignment-item', '.por-entregar',
                       '#aula-container', '[class*="tarea"]', '[class*="assignment"]',
                       '.actividades', 'ul.tareas'],
    'agenda':         ['.fc-view-container', '.fc-view', '.fc-daygrid',
                       '.fc-timegrid', '.calendar', '#calendar',
                       '[class*="fc-"]', '[class*="calendar"]', '.eventos-lista'],
}


# ─── UTILIDADES ──────────────────────────────────────────────────────────────

def _soup(driver):
    return BeautifulSoup(driver.page_source, 'lxml')

def _cookies(driver):
    return {c['name']: c['value'] for c in driver.get_cookies()}

def _es_leido(el):
    return any(c in el.get('class', []) for c in ['leido', 'read', 'opened'])

def _dias_hasta(fecha_str):
    if not fecha_str:
        return 999
    for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y']:
        try:
            return (datetime.strptime(fecha_str.strip()[:10], fmt).date() - date.today()).days
        except ValueError:
            pass
    return 999

def _nivel_urgencia(tipo, dias):
    es_eval = any(t in tipo.lower() for t in
                  ['examen','prueba','quiz','evaluacion','test','parcial'])
    if es_eval:
        if dias <= 0:  return 'CRITICA'
        if dias <= 2:  return 'CRITICA'
        if dias <= 5:  return 'ALTA'
        if dias <= 10: return 'MEDIA'
        return 'BAJA'
    else:
        if dias <= 0:  return 'ALTA'
        if dias <= 3:  return 'MEDIA'
        return 'BAJA'

def cargar_basal(key):
    ruta = Path(config.DIR_BASAL) / f'basal_{key}.json'
    if ruta.exists():
        try:
            return json.loads(ruta.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}

def guardar_basal(key, datos):
    Path(config.DIR_BASAL).mkdir(parents=True, exist_ok=True)
    (Path(config.DIR_BASAL) / f'basal_{key}.json').write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding='utf-8')


# ─── NAVEGACIÓN INTELIGENTE CON ESPERA DE CONTENIDO ─────────────────────────

def _navegar_y_esperar(driver, url, seccion_key, timeout_contenido=15):
    """
    Navega a la URL y espera que el CONTENIDO DINÁMICO cargue, no solo el body.
    Estrategia en cascada:
      1. Navegar y esperar body (confirma que la página respondió)
      2. Esperar document.readyState == 'complete'
      3. Intentar cada selector de contenido específico de la sección
      4. Si ninguno aparece en timeout_contenido segundos → espera fija adicional
    """
    if not wait_and_get(driver, url, 'body'):
        return False

    # Esperar que JS termine de cargar
    try:
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except TimeoutException:
        pass

    # Intentar cada selector específico de la sección
    selectores = SELECTORES_CONTENIDO.get(seccion_key, [])
    for sel in selectores:
        try:
            WebDriverWait(driver, timeout_contenido).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            logger.info(f"Contenido de '{seccion_key}' listo (selector: {sel})")
            time.sleep(1)   # pequeña pausa extra para renderizado completo
            return True
        except TimeoutException:
            continue

    # Ningún selector coincidió → esperar tiempo fijo y continuar igual
    logger.warning(
        f"'{seccion_key}': ningún selector de contenido encontrado en {timeout_contenido}s. "
        f"Esperando 5s adicionales y continuando.")
    time.sleep(5)

    # Log del HTML actual para diagnóstico
    try:
        soup_diag = BeautifulSoup(driver.page_source, 'lxml')
        clases_presentes = set()
        for tag in soup_diag.find_all(True, limit=200):
            for c in tag.get('class', []):
                clases_presentes.add(c)
        logger.info(f"'{seccion_key}' — clases CSS presentes: {sorted(clases_presentes)[:30]}")
    except Exception:
        pass

    return True   # Continuar aunque no hayamos confirmado el contenido


# ─── MENSAJES ────────────────────────────────────────────────────────────────

def revisar_mensajes(driver, ventana_desde, basal):
    url = config.BASE_URL + SECCIONES['mensajes']
    if not _navegar_y_esperar(driver, url, 'mensajes'):
        return [{'error': 'Seccion mensajes no disponible'}]

    soup = _soup(driver)
    filas = soup.select('tr.mensaje, tr.msg, .mensaje-fila, .message-row, li.mensaje')
    resultados = []

    for fila in filas:
        try:
            fecha_el  = (fila.select_one('.fecha, .date, td:nth-child(3)')
                         or fila.select_one('td:nth-child(2)'))
            fecha_txt = fecha_el.get_text(strip=True) if fecha_el else ''
            fecha_msg = None
            for fmt in ['%d/%m/%Y %H:%M','%Y-%m-%d %H:%M','%d-%m-%Y %H:%M',
                        '%d/%m/%Y','%Y-%m-%d']:
                try:
                    fecha_msg = datetime.strptime(fecha_txt.strip(), fmt).replace(tzinfo=TZ_CR)
                    break
                except ValueError:
                    pass
            if fecha_msg and fecha_msg < ventana_desde:
                continue

            leido        = _es_leido(fila)
            asunto_el    = fila.select_one('.asunto, .subject, .titulo, td:nth-child(1) a')
            remitente_el = fila.select_one('.remitente, .from, .sender, td:nth-child(2)')
            asunto    = asunto_el.get_text(strip=True)    if asunto_el    else 'Sin asunto'
            remitente = remitente_el.get_text(strip=True) if remitente_el else 'Desconocido'

            cuerpo = ''
            adjuntos_procesados = []
            link_el = fila.select_one('a[href]')
            if link_el:
                href    = link_el['href']
                url_msg = config.BASE_URL + href if href.startswith('/') else href
                if _navegar_y_esperar(driver, url_msg, 'mensajes'):
                    sm        = _soup(driver)
                    cuerpo_el = sm.select_one('.cuerpo,.body,.mensaje-body,#contenido-mensaje')
                    cuerpo    = cuerpo_el.get_text(separator='\n', strip=True) if cuerpo_el else ''
                    if len(cuerpo) < 30 and config.USAR_COMPUTER_USE:
                        cuerpo = analizar_pantalla_con_claude(driver,
                            'Lee el cuerpo completo de este mensaje y transcrIbelo integro.')
                    for adj in sm.select(
                        'a[href*=".pdf"],a[href*=".jpg"],a[href*=".png"],a[href*=".jpeg"]'):
                        adj_url = config.BASE_URL + adj['href'] if adj['href'].startswith('/') else adj['href']
                        adjuntos_procesados.append(
                            procesar_adjunto(adj_url,
                                             f"{asunto[:30]}_{adj['href'].split('/')[-1]}",
                                             _cookies(driver)))

            tc = (asunto + ' ' + cuerpo).lower()
            urg, razon = 'Baja', 'Sin palabras clave'
            for p in ['urgente','pago','suspension','expulsion','reunion',
                      'vence hoy','manana','evaluacion','falta']:
                if p in tc:
                    urg, razon = 'Alta', f'Contiene "{p}"'; break
            if urg == 'Baja':
                for p in ['examen','tarea','aviso','recordatorio','fecha limite']:
                    if p in tc:
                        urg, razon = 'Media', f'Contiene "{p}"'; break

            resultados.append({
                'asunto': asunto, 'remitente': remitente, 'fecha': fecha_txt,
                'cuerpo': cuerpo, 'adjuntos': adjuntos_procesados,
                'urgencia': urg, 'razon_urgencia': razon,
                'estado': '[YA LEIDO]' if leido else '[NUEVO]',
            })
        except Exception as e:
            logger.warning(f'Error mensaje: {e}')

    if not resultados and config.USAR_COMPUTER_USE:
        a = analizar_pantalla_con_claude(driver,
            'Lista todos los mensajes visibles: asunto, remitente, fecha, estado.')
        if a:
            resultados.append({'analisis_visual': a, 'estado': '[VISION]',
                                'urgencia': 'Media', 'razon_urgencia': 'Vision'})
    logger.info(f"Mensajes extraídos: {len(resultados)}")
    return resultados


# ─── CALIFICACIONES ──────────────────────────────────────────────────────────

def revisar_calificaciones(driver, basal):
    url = config.BASE_URL + SECCIONES['calificaciones']
    if not _navegar_y_esperar(driver, url, 'calificaciones'):
        return [{'error': 'Seccion calificaciones no disponible'}]

    soup        = _soup(driver)
    notas       = []
    basal_notas = basal.get('calificaciones', {})

    # Múltiples estrategias de extracción
    for selector in ['table.calificaciones tr', 'table tr',
                     '.calificacion-row', '.nota-row', 'tr']:
        filas = soup.select(selector)
        if len(filas) > 1:
            for fila in filas[1:]:
                celdas = fila.select('td')
                if len(celdas) >= 2:
                    materia = celdas[0].get_text(strip=True)
                    nota    = celdas[1].get_text(strip=True)
                    fecha   = celdas[2].get_text(strip=True) if len(celdas) > 2 else ''
                    if materia and nota and len(materia) > 1 and len(nota) < 20:
                        try:
                            nn = float(nota.replace(',','.')); est = 'Aprobada' if nn>=65 else 'REPROBADA'
                        except ValueError:
                            nn, est = None, ''
                        notas.append({
                            'materia': materia, 'nota': nota, 'nota_num': nn,
                            'nota_anterior': basal_notas.get(materia,'(sin historial)'),
                            'cambio': nota != basal_notas.get(materia),
                            'estado': est, 'fecha': fecha,
                        })
            if notas:
                break

    if not notas and config.USAR_COMPUTER_USE:
        a = analizar_pantalla_con_claude(driver,
            'Lista TODAS las calificaciones visibles. Para cada materia: nombre y nota.')
        if a:
            return [{'analisis_visual': a}]

    if not notas:
        # Guardar HTML para diagnóstico
        html_preview = soup.get_text(separator=' ', strip=True)[:400]
        logger.warning(f'Calificaciones vacías. HTML preview: {html_preview}')

    logger.info(f"Calificaciones extraídas: {len(notas)} materias")
    return notas


# ─── ASISTENCIA ──────────────────────────────────────────────────────────────

def revisar_asistencia(driver, basal):
    url = config.BASE_URL + SECCIONES['asistencia']
    if not _navegar_y_esperar(driver, url, 'asistencia'):
        return {'error': 'Asistencia no disponible', 'porcentaje': None,
                'total_ausencias': 0, 'riesgo': False, 'detalle': []}

    soup   = _soup(driver)
    result = {'porcentaje': None, 'total_ausencias': 0, 'riesgo': False, 'detalle': []}

    for sel in ['.porcentaje-asistencia','.pct-asistencia','.attendance-pct',
                'td.porcentaje','span.porcentaje','.total-asistencia','strong','b']:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(strip=True)
            if '%' in txt:
                result['porcentaje'] = txt
                try:
                    pct = float(txt.replace('%','').replace(',','.').strip())
                    result['riesgo'] = pct < 85
                except ValueError:
                    pass
                break

    for fila in soup.select('table tr,.asistencia-row')[1:]:
        celdas = fila.select('td')
        if len(celdas) >= 2:
            m = celdas[0].get_text(strip=True)
            a = celdas[1].get_text(strip=True)
            p = celdas[2].get_text(strip=True) if len(celdas) > 2 else ''
            if m and len(m) > 1:
                try: result['total_ausencias'] += int(a)
                except ValueError: pass
                result['detalle'].append({'materia': m, 'ausencias': a, 'pct': p})

    if not result['detalle'] and config.USAR_COMPUTER_USE:
        a = analizar_pantalla_con_claude(driver,
            'Extrae el porcentaje de asistencia y ausencias por materia.')
        result['analisis_visual'] = a

    logger.info(f"Asistencia: {result['porcentaje']} | ausencias: {result['total_ausencias']}")
    return result


# ─── SECCIÓN SIMPLE ──────────────────────────────────────────────────────────

def revisar_seccion_simple(driver, seccion_key, basal, pregunta_claude):
    url = config.BASE_URL + SECCIONES[seccion_key]
    if not _navegar_y_esperar(driver, url, seccion_key):
        return [{'error': f'Seccion {seccion_key} no disponible'}]
    soup  = _soup(driver)
    items = []
    for fila in soup.select('table tr,.fila,.row-item,li')[1:]:
        txt = fila.get_text(separator=' | ', strip=True)
        if txt and len(txt) > 3:
            items.append({'detalle': txt})
    if not items and config.USAR_COMPUTER_USE:
        a = analizar_pantalla_con_claude(driver, pregunta_claude)
        if a:
            items.append({'analisis_visual': a})
    return items


# ─── AULA VIRTUAL ─────────────────────────────────────────────────────────────

def _extraer_detalle_tarea(driver, url_tarea, url_lista):
    if not _navegar_y_esperar(driver, url_tarea, 'aula_virtual'):
        return {}
    soup = _soup(driver)
    ins  = ''
    for sel in ['.instrucciones','.description','.tarea-body',
                '#tarea-contenido','.assignment-description','.contenido']:
        el = soup.select_one(sel)
        if el:
            ins = el.get_text(separator='\n', strip=True)
            if len(ins) > 20: break
    if len(ins) < 30 and config.USAR_COMPUTER_USE:
        ins = analizar_pantalla_con_claude(driver,
            'Cuales son las instrucciones completas de esta tarea?')
    adjs = []
    for adj in soup.select('a[href*=".pdf"],a[href*=".docx"],a[href*=".doc"]'):
        adj_url = config.BASE_URL + adj['href'] if adj['href'].startswith('/') else adj['href']
        adjs.append({'nombre': adj.get_text(strip=True) or adj['href'].split('/')[-1],
                     'url': adj_url})
    _navegar_y_esperar(driver, url_lista, 'aula_virtual')
    return {'instrucciones': ins[:600], 'adjuntos': adjs}


def revisar_aula_virtual(driver, ventana_desde, basal):
    url = config.BASE_URL + SECCIONES['aula_virtual']
    if not _navegar_y_esperar(driver, url, 'aula_virtual'):
        return {'error': 'Aula virtual no disponible'}

    soup   = _soup(driver)
    tareas = []
    for sel in ['.tarea-item','.assignment-item','.task-item',
                '.por-entregar .tarea','li.tarea','tr.tarea']:
        items_html = soup.select(sel)
        if items_html:
            for item in items_html[:8]:
                ne = item.select_one('.nombre,.title,.tarea-nombre,a')
                fe = item.select_one('.fecha,.due-date,.vencimiento,.fecha-limite')
                me = item.select_one('.materia,.subject,.curso,.asignatura')
                le = item.select_one('a[href]')
                nombre  = ne.get_text(strip=True) if ne else 'Sin nombre'
                fecha   = fe.get_text(strip=True) if fe else ''
                materia = me.get_text(strip=True) if me else ''
                dias    = _dias_hasta(fecha)
                det     = {}
                if le and le.get('href'):
                    href  = le['href']
                    url_t = config.BASE_URL + href if href.startswith('/') else href
                    det   = _extraer_detalle_tarea(driver, url_t, url)
                tareas.append({
                    'nombre': nombre, 'materia': materia,
                    'fecha_limite': fecha, 'dias_restantes': dias,
                    'estado': 'atrasada' if dias < 0 else 'pendiente',
                    'instrucciones': det.get('instrucciones',''),
                    'materiales': det.get('adjuntos',[]),
                })
            break

    if not tareas and config.USAR_COMPUTER_USE:
        a = analizar_pantalla_con_claude(driver,
            'Lista todas las tareas pendientes con nombre, materia, fecha limite.')
        tareas = [{'analisis_visual': a}] if a else []

    atrasadas = len([t for t in tareas if isinstance(t,dict) and t.get('estado')=='atrasada'])
    logger.info(f"Aula virtual: {len(tareas)} tareas, {atrasadas} atrasadas")
    return {'tareas': tareas, 'total_pendientes': len(tareas), 'total_atrasadas': atrasadas}


# ─── AGENDA ──────────────────────────────────────────────────────────────────

def _extraer_temario_evento(driver, url_evento, url_agenda):
    if not url_evento or not _navegar_y_esperar(driver, url_evento, 'agenda'):
        return []
    soup    = _soup(driver)
    temario = []
    for sel in ['.temario li','.objetivos li','.contenido li',
                '.event-description li','ul.temas li','#evento-detalle li',
                'ul li','ol li']:
        items = soup.select(sel)
        if items and len(items) >= 2:
            temario = [i.get_text(strip=True) for i in items if len(i.get_text(strip=True)) > 3]
            if temario: break
    if not temario:
        for sel in ['.event-description','.descripcion','.contenido',
                    '#evento-detalle','.temario','.card-body','.panel-body']:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(separator='\n', strip=True)
                if len(txt) > 20:
                    temario = [l.strip() for l in txt.splitlines() if len(l.strip()) > 3]
                    break
    if not temario and config.USAR_COMPUTER_USE:
        a = analizar_pantalla_con_claude(driver,
            'Extrae el temario completo de esta evaluacion. Lista cada tema en una linea.')
        if a:
            temario = [l.strip() for l in a.splitlines() if len(l.strip()) > 3]
    _navegar_y_esperar(driver, url_agenda, 'agenda')
    return temario[:25]


def revisar_agenda(driver, basal):
    """
    Extrae eventos del calendario esperando el contenido dinámico (FullCalendar/SPA).
    """
    url = config.BASE_URL + SECCIONES['agenda']
    if not _navegar_y_esperar(driver, url, 'agenda', timeout_contenido=20):
        return [{'error': 'Seccion agenda no disponible'}]

    # Espera extra para que FullCalendar renderice todos los eventos
    time.sleep(3)

    soup        = _soup(driver)
    eventos_raw = []

    # FullCalendar selectores
    for sel in ['.fc-event','.fc-daygrid-event','.fc-timegrid-event',
                '.fc-list-event','.fc-event-title','a.fc-event',
                '[class*="fc-event"]']:
        elementos = soup.select(sel)
        if elementos:
            logger.info(f"Agenda: {len(elementos)} eventos via '{sel}'")
            for el in elementos:
                texto = el.get_text(separator=' ', strip=True)
                href  = el.get('href','')
                fecha = ''
                for attr in ['data-date','data-start','data-evento-fecha','data-day']:
                    v = el.get(attr,'')
                    if v: fecha = v[:10]; break
                if not fecha:
                    for padre in [el.parent, el.parent.parent if el.parent else None]:
                        if padre:
                            for attr in ['data-date','data-day','data-start']:
                                v = padre.get(attr,'')
                                if v: fecha = v[:10]; break
                        if fecha: break
                if texto and len(texto) > 2:
                    eventos_raw.append({'texto': texto, 'href': href, 'fecha_raw': fecha})
            if eventos_raw: break

    # Contenedores alternativos
    if not eventos_raw:
        for sel in ['.calendar-event','.evento-item','a.event-link','.event',
                    '[class*="event"]','[class*="evento"]',
                    '.fc-list-item','.fc-h-event','td[data-date] a',
                    'td[data-day] a']:
            elementos = soup.select(sel)
            if elementos:
                for el in elementos:
                    texto = el.get_text(separator=' ', strip=True)
                    if texto and len(texto) > 2:
                        eventos_raw.append({
                            'texto': texto, 'href': el.get('href',''),
                            'fecha_raw': el.get('data-date','') or el.get('data-start','')
                        })
                if eventos_raw: break

    # Log diagnóstico
    if not eventos_raw:
        clases = set()
        for tag in soup.find_all(True, limit=300):
            for c in tag.get('class', []):
                clases.add(c)
        logger.warning(f"Agenda vacía. Clases CSS presentes: {sorted(clases)[:40]}")
        ids = [tag.get('id') for tag in soup.find_all(True) if tag.get('id')]
        logger.warning(f"IDs presentes: {ids[:20]}")

    # Fallback Claude Vision
    if not eventos_raw and config.USAR_COMPUTER_USE:
        a = analizar_pantalla_con_claude(driver,
            'Lista TODOS los eventos del calendario. Para cada uno responde SOLO JSON: '
            '[{"titulo":"","fecha":"dd/mm/yyyy","tipo":"examen|quiz|prueba|tarea|actividad","materia":""}]')
        if a:
            try:
                txt = re.sub(r'```[a-z]*','',a).strip().strip('`')
                evs = json.loads(txt)
                if isinstance(evs, list):
                    procesados = []
                    for ev in evs:
                        dias = _dias_hasta(ev.get('fecha',''))
                        tipo = ev.get('tipo','actividad')
                        procesados.append({
                            'titulo': ev.get('titulo',''), 'materia': ev.get('materia',''),
                            'tipo': tipo, 'fecha': ev.get('fecha',''),
                            'dias_restantes': dias,
                            'urgencia': _nivel_urgencia(tipo, dias), 'temario': [],
                        })
                    procesados.sort(key=lambda x: (
                        {'CRITICA':0,'ALTA':1,'MEDIA':2,'BAJA':3}.get(x['urgencia'],4),
                        x['dias_restantes']))
                    return procesados
            except (json.JSONDecodeError, ValueError):
                return [{'analisis_visual': a, 'tipo': 'agenda_detallada'}]
        return [{'error': 'No se detectaron eventos. El calendario requiere JavaScript dinámico y Computer Use está desactivado. Configurar ANTHROPIC_API_KEY en GitHub Secrets.'}]

    if not eventos_raw:
        return [{'error': 'No se detectaron eventos. El calendario requiere JavaScript dinámico. Configurar ANTHROPIC_API_KEY en GitHub Secrets para usar Computer Use.'}]

    # Procesar eventos
    procesados = []
    for ev in eventos_raw[:15]:
        titulo = ev['texto']
        tl     = titulo.lower()
        fecha  = ev.get('fecha_raw','')
        dias   = _dias_hasta(fecha)

        if any(t in tl for t in ['examen','parcial']):  tipo = 'examen'
        elif 'quiz' in tl:                               tipo = 'quiz'
        elif 'prueba' in tl:                             tipo = 'prueba'
        elif any(t in tl for t in ['tarea','trabajo','proyecto','entrega']): tipo = 'tarea'
        elif any(t in tl for t in ['feriado','asueto','libre']): tipo = 'feriado'
        else:                                            tipo = 'actividad'

        materia = titulo
        for pt in ['quiz','examen','prueba','tarea','trabajo','proyecto','parcial']:
            materia = materia.lower().replace(pt,'').strip().title()

        temario = []
        if tipo in ('examen','quiz','prueba','tarea') and ev.get('href'):
            href    = ev['href']
            url_det = config.BASE_URL + href if href.startswith('/') else href
            temario = _extraer_temario_evento(driver, url_det, url)

        procesados.append({
            'titulo': titulo, 'materia': materia, 'tipo': tipo,
            'fecha': fecha, 'dias_restantes': dias,
            'urgencia': _nivel_urgencia(tipo, dias), 'temario': temario,
        })

    procesados.sort(key=lambda x: (
        {'CRITICA':0,'ALTA':1,'MEDIA':2,'BAJA':3}.get(x['urgencia'],4),
        x['dias_restantes']))
    logger.info(f"Agenda: {len(procesados)} eventos procesados")
    return procesados


# ─── ORQUESTADOR ─────────────────────────────────────────────────────────────

def revisar_estudiante(driver, label, grado, nombre_corto, ventana_desde, basal):
    datos = {'estudiante': label, 'nombre_corto': nombre_corto, 'grado': grado}
    logger.info(f"=== Revisando {label} ===")
    datos['mensajes']       = revisar_mensajes(driver, ventana_desde, basal)
    datos['calificaciones'] = revisar_calificaciones(driver, basal)
    datos['asistencia']     = revisar_asistencia(driver, basal)
    datos['boleta']         = revisar_seccion_simple(driver, 'boleta', basal,
        'Registros de conducta y boleta disponibles.')
    datos['anotaciones']    = revisar_seccion_simple(driver, 'anotaciones', basal,
        'Lista todas las anotaciones con fecha, tipo y descripcion.')
    datos['aula_virtual']   = revisar_aula_virtual(driver, ventana_desde, basal)
    datos['agenda']         = revisar_agenda(driver, basal)
    return datos
