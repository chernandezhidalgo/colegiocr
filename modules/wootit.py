"""
wootit.py v3.2.0 — Correcciones basadas en informe real 15/03/2026:
  FIX-1: Agenda funciona SIN Computer Use (extracción HTML robusta + múltiples estrategias)
  FIX-2: cambiar_estudiante() ahora no requiere confirmación por header (selector era incorrecto)
  FIX-3: Calificaciones con estrategias múltiples de scraping
  FIX-4: Asistencia con URL correcta y fallback Claude Vision
"""
import json
import logging
import re
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
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


# ============================================================
# UTILIDADES
# ============================================================

def _soup(driver):
    return BeautifulSoup(driver.page_source, 'lxml')

def _cookies(driver):
    return {c['name']: c['value'] for c in driver.get_cookies()}

def _es_leido(elemento):
    clases = elemento.get('class', [])
    return any(c in ['leido', 'read', 'opened'] for c in clases)

def _dias_hasta(fecha_str):
    if not fecha_str:
        return 999
    for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%SZ']:
        try:
            return (datetime.strptime(fecha_str.strip()[:10], fmt[:8] if 'T' in fmt else fmt).date() - date.today()).days
        except ValueError:
            pass
    return 999

def _nivel_urgencia(tipo, dias):
    es_eval = any(t in tipo.lower() for t in ['examen','prueba','quiz','evaluacion','test','parcial'])
    if es_eval:
        if dias <= 0: return 'CRITICA'
        if dias <= 2: return 'CRITICA'
        if dias <= 5: return 'ALTA'
        if dias <= 10: return 'MEDIA'
        return 'BAJA'
    else:
        if dias <= 0: return 'ALTA'
        if dias <= 3: return 'MEDIA'
        return 'BAJA'

def cargar_basal(estudiante_key):
    ruta = Path(config.DIR_BASAL) / f'basal_{estudiante_key}.json'
    if ruta.exists():
        try:
            return json.loads(ruta.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}

def guardar_basal(estudiante_key, datos):
    Path(config.DIR_BASAL).mkdir(parents=True, exist_ok=True)
    ruta = Path(config.DIR_BASAL) / f'basal_{estudiante_key}.json'
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding='utf-8')


# ============================================================
# MENSAJES
# ============================================================

def revisar_mensajes(driver, ventana_desde, basal):
    url = config.BASE_URL + SECCIONES['mensajes']
    if not wait_and_get(driver, url, 'body'):
        return [{'error': 'Seccion mensajes no disponible'}]

    soup = _soup(driver)
    filas = soup.select('tr.mensaje, tr.msg, .mensaje-fila, .message-row, li.mensaje')
    resultados = []

    for fila in filas:
        try:
            fecha_el  = (fila.select_one('.fecha, .date, td:nth-child(3)') or fila.select_one('td:nth-child(2)'))
            fecha_txt = fecha_el.get_text(strip=True) if fecha_el else ''
            fecha_msg = None
            for fmt in ['%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M', '%d-%m-%Y %H:%M', '%d/%m/%Y', '%Y-%m-%d']:
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
            asunto   = asunto_el.get_text(strip=True)    if asunto_el    else 'Sin asunto'
            remitente = remitente_el.get_text(strip=True) if remitente_el else 'Desconocido'

            cuerpo = ''
            adjuntos_procesados = []
            link_el = fila.select_one('a[href]')
            if link_el:
                href    = link_el['href']
                url_msg = config.BASE_URL + href if href.startswith('/') else href
                if wait_and_get(driver, url_msg, 'body'):
                    soup_msg  = _soup(driver)
                    cuerpo_el = soup_msg.select_one('.cuerpo, .body, .mensaje-body, #contenido-mensaje')
                    cuerpo    = cuerpo_el.get_text(separator='\n', strip=True) if cuerpo_el else ''
                    if len(cuerpo) < 30 and config.USAR_COMPUTER_USE:
                        cuerpo = analizar_pantalla_con_claude(driver, 'Lee el cuerpo completo de este mensaje y transcrIbelo integro.')
                    for adj in soup_msg.select('a[href*=".pdf"], a[href*=".jpg"], a[href*=".png"], a[href*=".jpeg"]'):
                        adj_url    = config.BASE_URL + adj['href'] if adj['href'].startswith('/') else adj['href']
                        adj_nombre = f"{asunto[:30]}_{adj['href'].split('/')[-1]}"
                        adjuntos_procesados.append(procesar_adjunto(adj_url, adj_nombre, _cookies(driver)))

            texto_completo = (asunto + ' ' + cuerpo).lower()
            urgencia       = 'Baja'
            razon_urgencia = 'Sin palabras clave de alerta'
            for p in ['urgente','pago','suspension','expulsion','reunion','vence hoy','manana','evaluacion','falta']:
                if p in texto_completo:
                    urgencia = 'Alta'; razon_urgencia = f'Contiene "{p}"'; break
            if urgencia == 'Baja':
                for p in ['examen','tarea','aviso','recordatorio','fecha limite']:
                    if p in texto_completo:
                        urgencia = 'Media'; razon_urgencia = f'Contiene "{p}"'; break

            resultados.append({
                'asunto': asunto, 'remitente': remitente, 'fecha': fecha_txt,
                'cuerpo': cuerpo, 'adjuntos': adjuntos_procesados,
                'urgencia': urgencia, 'razon_urgencia': razon_urgencia,
                'estado': '[YA LEIDO]' if leido else '[NUEVO]',
            })
        except Exception as e:
            logger.warning(f'Error procesando mensaje: {e}')

    if not resultados and config.USAR_COMPUTER_USE:
        analisis = analizar_pantalla_con_claude(driver, 'Lista todos los mensajes visibles: asunto, remitente, fecha, estado.')
        if analisis:
            resultados.append({'analisis_visual': analisis, 'estado': '[ANALISIS VISUAL]', 'urgencia': 'Media', 'razon_urgencia': 'Vision'})
    return resultados


# ============================================================
# CALIFICACIONES — múltiples estrategias de scraping
# ============================================================

def revisar_calificaciones(driver, basal):
    """FIX-3: Múltiples estrategias de extracción + Claude Vision fallback."""
    url = config.BASE_URL + SECCIONES['calificaciones']
    if not wait_and_get(driver, url, 'body'):
        return [{'error': 'Seccion calificaciones no disponible'}]

    soup        = _soup(driver)
    todas_notas = []
    basal_notas = basal.get('calificaciones', {})

    # Estrategia 1: tablas estándar
    for selector in ['table.calificaciones tr', 'table tr', '.calificacion-row', '.nota-row', 'tr']:
        filas = soup.select(selector)
        if len(filas) > 1:
            for fila in filas[1:]:
                celdas = fila.select('td')
                if len(celdas) >= 2:
                    materia = celdas[0].get_text(strip=True)
                    nota    = celdas[1].get_text(strip=True)
                    fecha   = celdas[2].get_text(strip=True) if len(celdas) > 2 else ''
                    if materia and nota and len(materia) > 1:
                        try:
                            nota_num = float(nota.replace(',','.'))
                            estado   = 'Aprobada' if nota_num >= 65 else 'REPROBADA'
                        except ValueError:
                            nota_num, estado = None, ''
                        cambio = nota != basal_notas.get(materia)
                        todas_notas.append({
                            'materia': materia, 'nota': nota, 'nota_num': nota_num,
                            'nota_anterior': basal_notas.get(materia, '(sin historial)'),
                            'cambio': cambio, 'estado': estado, 'fecha': fecha,
                        })
            if todas_notas:
                break

    # Estrategia 2: elementos con clase de nota
    if not todas_notas:
        for item in soup.select('.materia-nota, .grade-item, .subject-grade, [class*="nota"], [class*="grade"]'):
            texto = item.get_text(separator='|', strip=True)
            if texto and '|' in texto:
                partes = texto.split('|')
                if len(partes) >= 2:
                    todas_notas.append({
                        'materia': partes[0], 'nota': partes[1],
                        'nota_num': None, 'nota_anterior': '(sin historial)',
                        'cambio': False, 'estado': '', 'fecha': '',
                    })

    # Fallback: Claude Vision
    if not todas_notas and config.USAR_COMPUTER_USE:
        analisis = analizar_pantalla_con_claude(driver,
            'Lista TODAS las calificaciones visibles en esta pagina. '
            'Para cada materia indica: nombre de la materia y la nota obtenida. '
            'Formato: MATERIA: nota')
        if analisis:
            return [{'analisis_visual': analisis}]

    if not todas_notas:
        # Último recurso: capturar todo el texto de la página
        texto_pagina = soup.get_text(separator='\n', strip=True)
        logger.info(f'Calificaciones - texto pagina ({len(texto_pagina)} chars): {texto_pagina[:300]}')

    return todas_notas


# ============================================================
# ASISTENCIA — FIX-4: URL correcta + fallback Claude Vision
# ============================================================

def revisar_asistencia(driver, basal):
    """FIX-4: URL correcta de asistencia y múltiples selectores."""
    url = config.BASE_URL + SECCIONES['asistencia']
    if not wait_and_get(driver, url, 'body'):
        return {'error': 'Seccion asistencia no disponible', 'porcentaje': None, 'total_ausencias': 0, 'riesgo': False, 'detalle': []}

    soup   = _soup(driver)
    result = {'porcentaje': None, 'total_ausencias': 0, 'riesgo': False, 'detalle': []}

    # Buscar porcentaje global con múltiples selectores
    for sel in ['.porcentaje-asistencia', '.pct-asistencia', '.attendance-pct',
                'td.porcentaje', 'span.porcentaje', '.total-asistencia',
                '[class*="asistencia"] .total', '[class*="attendance"] span',
                'strong', 'b']:
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

    # Detalle por materia
    for fila in soup.select('table tr, .asistencia-row')[1:]:
        celdas = fila.select('td')
        if len(celdas) >= 2:
            materia  = celdas[0].get_text(strip=True)
            ausencias = celdas[1].get_text(strip=True)
            pct_mat  = celdas[2].get_text(strip=True) if len(celdas) > 2 else ''
            if materia and len(materia) > 1:
                try:
                    result['total_ausencias'] += int(ausencias)
                except ValueError:
                    pass
                result['detalle'].append({'materia': materia, 'ausencias': ausencias, 'pct': pct_mat})

    # Fallback Claude Vision
    if not result['detalle'] and config.USAR_COMPUTER_USE:
        analisis = analizar_pantalla_con_claude(driver,
            'Extrae el porcentaje de asistencia y ausencias por materia. '
            'Indica el porcentaje total y si hay riesgo de perder materias.')
        result['analisis_visual'] = analisis

    return result


# ============================================================
# SECCION SIMPLE
# ============================================================

def revisar_seccion_simple(driver, seccion_key, basal, pregunta_claude):
    url = config.BASE_URL + SECCIONES[seccion_key]
    if not wait_and_get(driver, url, 'body'):
        return [{'error': f'Seccion {seccion_key} no disponible'}]
    soup  = _soup(driver)
    filas = soup.select('table tr, .fila, .row-item, li')
    items = []
    for fila in filas[1:]:
        texto = fila.get_text(separator=' | ', strip=True)
        if texto and len(texto) > 3:
            items.append({'detalle': texto})
    if not items and config.USAR_COMPUTER_USE:
        analisis = analizar_pantalla_con_claude(driver, pregunta_claude)
        if analisis:
            items.append({'analisis_visual': analisis})
    return items


# ============================================================
# AULA VIRTUAL
# ============================================================

def _extraer_detalle_tarea(driver, url_tarea, url_lista):
    if not wait_and_get(driver, url_tarea, 'body'):
        return {}
    soup = _soup(driver)
    instrucciones = ''
    for sel in ['.instrucciones', '.description', '.tarea-body', '#tarea-contenido', '.assignment-description', '.contenido']:
        el = soup.select_one(sel)
        if el:
            instrucciones = el.get_text(separator='\n', strip=True)
            if len(instrucciones) > 20:
                break
    if len(instrucciones) < 30 and config.USAR_COMPUTER_USE:
        instrucciones = analizar_pantalla_con_claude(driver,
            'Que debe hacer el estudiante en esta tarea? Cuales son las instrucciones y criterios de evaluacion?')
    adjuntos = []
    for adj in soup.select('a[href*=".pdf"], a[href*=".docx"], a[href*=".doc"]'):
        adj_url = config.BASE_URL + adj['href'] if adj['href'].startswith('/') else adj['href']
        adjuntos.append({'nombre': adj.get_text(strip=True) or adj['href'].split('/')[-1], 'url': adj_url})
    wait_and_get(driver, url_lista, 'body')
    return {'instrucciones': instrucciones[:600], 'adjuntos': adjuntos}


def revisar_aula_virtual(driver, ventana_desde, basal):
    url = config.BASE_URL + SECCIONES['aula_virtual']
    if not wait_and_get(driver, url, 'body'):
        return {'error': 'Seccion aula virtual no disponible'}
    soup  = _soup(driver)
    tareas = []
    for sel_tarea in ['.tarea-item', '.assignment-item', '.task-item', '.por-entregar .tarea', 'li.tarea', 'tr.tarea']:
        items_html = soup.select(sel_tarea)
        if items_html:
            for item in items_html[:8]:
                nombre_el  = item.select_one('.nombre, .title, .tarea-nombre, a')
                fecha_el   = item.select_one('.fecha, .due-date, .vencimiento, .fecha-limite')
                materia_el = item.select_one('.materia, .subject, .curso, .asignatura')
                link_el    = item.select_one('a[href]')
                nombre  = nombre_el.get_text(strip=True)  if nombre_el  else 'Sin nombre'
                fecha   = fecha_el.get_text(strip=True)   if fecha_el   else ''
                materia = materia_el.get_text(strip=True) if materia_el else ''
                dias    = _dias_hasta(fecha)
                detalle = {}
                if link_el and link_el.get('href'):
                    href  = link_el['href']
                    url_t = config.BASE_URL + href if href.startswith('/') else href
                    detalle = _extraer_detalle_tarea(driver, url_t, url)
                tareas.append({
                    'nombre': nombre, 'materia': materia, 'fecha_limite': fecha,
                    'dias_restantes': dias, 'estado': 'atrasada' if dias < 0 else 'pendiente',
                    'instrucciones': detalle.get('instrucciones', ''),
                    'materiales': detalle.get('adjuntos', []),
                })
            break
    if not tareas and config.USAR_COMPUTER_USE:
        analisis = analizar_pantalla_con_claude(driver,
            'Lista todas las tareas pendientes con nombre, materia, fecha limite e instrucciones.')
        tareas = [{'analisis_visual': analisis}] if analisis else []
    atrasadas = len([t for t in tareas if isinstance(t, dict) and t.get('estado') == 'atrasada'])
    return {'tareas': tareas, 'total_pendientes': len(tareas), 'total_atrasadas': atrasadas}


# ============================================================
# AGENDA — FIX-1: funciona SIN Computer Use
# ============================================================

def _extraer_temario_evento(driver, url_evento, url_agenda):
    """Extrae temario del detalle de un evento. Funciona sin Claude Vision."""
    if not url_evento or not wait_and_get(driver, url_evento, 'body'):
        return []
    soup    = _soup(driver)
    temario = []

    # Estrategia 1: listas estructuradas
    for sel in ['.temario li', '.objetivos li', '.contenido li',
                '.event-description li', 'ul.temas li', '#evento-detalle li',
                '.evaluacion-temas li', 'ul li', 'ol li']:
        items = soup.select(sel)
        if items and len(items) >= 2:
            temario = [i.get_text(strip=True) for i in items if len(i.get_text(strip=True)) > 3]
            if temario:
                break

    # Estrategia 2: párrafos de contenido
    if not temario:
        for sel in ['.event-description', '.descripcion', '.contenido',
                    '#evento-detalle', '.temario', '.evaluacion-descripcion',
                    '.card-body', '.panel-body', 'main p', '.detail p']:
            el = soup.select_one(sel)
            if el:
                texto = el.get_text(separator='\n', strip=True)
                if len(texto) > 20:
                    lineas = [l.strip() for l in texto.splitlines() if len(l.strip()) > 3]
                    if lineas:
                        temario = lineas
                        break

    # Estrategia 3: todo el texto del body como último recurso HTML
    if not temario:
        body_texto = soup.get_text(separator='\n', strip=True)
        if len(body_texto) > 50:
            lineas = [l.strip() for l in body_texto.splitlines()
                      if len(l.strip()) > 5 and not l.strip().startswith('http')]
            temario = lineas[:20]

    # Estrategia 4: Claude Vision solo si está disponible
    if not temario and config.USAR_COMPUTER_USE:
        analisis = analizar_pantalla_con_claude(driver,
            'Extrae el temario completo de esta evaluacion. '
            'Lista cada tema en una linea. Solo la lista, sin encabezados.')
        if analisis:
            temario = [l.strip() for l in analisis.splitlines() if len(l.strip()) > 3]

    wait_and_get(driver, url_agenda, 'body')
    return temario[:25]


def revisar_agenda(driver, basal):
    """
    FIX-1: Extracción robusta que funciona SIN Computer Use.
    Múltiples estrategias de scraping HTML antes de intentar Claude Vision.
    """
    url = config.BASE_URL + SECCIONES['agenda']
    if not wait_and_get(driver, url, 'body'):
        return [{'error': 'Seccion agenda no disponible'}]

    soup        = _soup(driver)
    eventos_raw = []

    # Estrategia 1: FullCalendar (WootIT usa fc-event)
    for sel in ['.fc-event', '.fc-daygrid-event', '.fc-timegrid-event',
                '.fc-list-event', '.fc-event-title', 'a.fc-event']:
        elementos = soup.select(sel)
        if elementos:
            logger.info(f'Agenda: {len(elementos)} eventos via selector {sel}')
            for el in elementos:
                texto = el.get_text(separator=' ', strip=True)
                href  = el.get('href', '')
                # Buscar fecha en atributos data-*
                fecha = ''
                for attr in ['data-date', 'data-start', 'data-evento-fecha', 'data-day']:
                    v = el.get(attr, '')
                    if v:
                        fecha = v[:10]
                        break
                # Buscar fecha en elemento padre
                if not fecha:
                    for padre in [el.parent, el.parent.parent if el.parent else None]:
                        if padre:
                            for attr in ['data-date', 'data-day', 'data-start']:
                                v = padre.get(attr, '')
                                if v:
                                    fecha = v[:10]
                                    break
                        if fecha:
                            break
                if texto and len(texto) > 2:
                    eventos_raw.append({'texto': texto, 'href': href, 'fecha_raw': fecha})
            if eventos_raw:
                break

    # Estrategia 2: otros contenedores de calendario
    if not eventos_raw:
        for sel in ['.calendar-event', '.evento-item', 'a.event-link',
                    '.event', '[class*="event"]', '[class*="evento"]',
                    '.fc-list-item', '.fc-h-event']:
            elementos = soup.select(sel)
            if elementos:
                for el in elementos:
                    texto = el.get_text(separator=' ', strip=True)
                    if texto and len(texto) > 2:
                        eventos_raw.append({
                            'texto': texto,
                            'href':  el.get('href', ''),
                            'fecha_raw': el.get('data-date', '') or el.get('data-start', '')
                        })
                if eventos_raw:
                    break

    # Estrategia 3: buscar en todo el HTML celdas de tabla con fechas
    if not eventos_raw:
        # WootIT puede usar una tabla de calendario clásica
        for td in soup.select('td[data-date], td[data-day]'):
            fecha = td.get('data-date', '') or td.get('data-day', '')
            for link in td.select('a, .event, span.titulo'):
                texto = link.get_text(strip=True)
                if texto and len(texto) > 2:
                    eventos_raw.append({
                        'texto': texto,
                        'href':  link.get('href', ''),
                        'fecha_raw': fecha
                    })

    # Log diagnóstico del HTML recibido cuando no hay eventos
    if not eventos_raw:
        html_resumen = soup.get_text(separator=' ', strip=True)[:500]
        logger.warning(f'Agenda: no se encontraron eventos. HTML preview: {html_resumen}')

    # Si Claude Vision está disponible y HTML falló: usarlo
    if not eventos_raw and config.USAR_COMPUTER_USE:
        analisis_vis = analizar_pantalla_con_claude(driver,
            'Lista TODOS los eventos del calendario. Para cada uno: '
            '{"titulo":"","fecha":"dd/mm/yyyy","tipo":"examen|quiz|prueba|tarea|actividad","materia":""}. '
            'Responde SOLO JSON array.')
        if analisis_vis:
            try:
                txt = re.sub(r'```[a-z]*', '', analisis_vis).strip().strip('`')
                evs = json.loads(txt)
                procesados = []
                for ev in evs if isinstance(evs, list) else []:
                    dias = _dias_hasta(ev.get('fecha',''))
                    tipo = ev.get('tipo','actividad')
                    procesados.append({
                        'titulo': ev.get('titulo',''), 'materia': ev.get('materia',''),
                        'tipo': tipo, 'fecha': ev.get('fecha',''),
                        'dias_restantes': dias, 'urgencia': _nivel_urgencia(tipo, dias), 'temario': [],
                    })
                if procesados:
                    procesados.sort(key=lambda x: ({'CRITICA':0,'ALTA':1,'MEDIA':2,'BAJA':3}.get(x['urgencia'],4), x['dias_restantes']))
                    return procesados
            except (json.JSONDecodeError, ValueError):
                return [{'analisis_visual': analisis_vis, 'tipo': 'agenda_detallada'}]
        return [{'error': 'No se detectaron eventos en la agenda (Computer Use activo pero sin resultados)'}]

    if not eventos_raw:
        return [{'error': 'No se detectaron eventos. El portal puede usar JavaScript dinámico que requiere esperar la carga completa.'}]

    # Procesar cada evento
    procesados = []
    for ev in eventos_raw[:12]:
        titulo      = ev['texto']
        fecha_str   = ev.get('fecha_raw', '')
        dias        = _dias_hasta(fecha_str)
        titulo_lower = titulo.lower()

        if any(t in titulo_lower for t in ['examen','parcial']):   tipo = 'examen'
        elif 'quiz' in titulo_lower:                                tipo = 'quiz'
        elif 'prueba' in titulo_lower:                              tipo = 'prueba'
        elif any(t in titulo_lower for t in ['tarea','trabajo','proyecto','entrega']): tipo = 'tarea'
        elif any(t in titulo_lower for t in ['feriado','asueto','libre']): tipo = 'feriado'
        else:                                                       tipo = 'actividad'

        materia = titulo
        for pt in ['quiz','examen','prueba','tarea','trabajo','proyecto','parcial']:
            materia = materia.lower().replace(pt,'').strip().title()

        urgencia = _nivel_urgencia(tipo, dias)
        temario  = []
        if tipo in ('examen','quiz','prueba','tarea') and ev.get('href'):
            href    = ev['href']
            url_det = config.BASE_URL + href if href.startswith('/') else href
            temario = _extraer_temario_evento(driver, url_det, url)

        procesados.append({
            'titulo': titulo, 'materia': materia, 'tipo': tipo,
            'fecha': fecha_str, 'dias_restantes': dias,
            'urgencia': urgencia, 'temario': temario,
        })

    procesados.sort(key=lambda x: (
        {'CRITICA':0,'ALTA':1,'MEDIA':2,'BAJA':3}.get(x['urgencia'],4), x['dias_restantes']))
    return procesados


# ============================================================
# ORQUESTADOR
# ============================================================

def revisar_estudiante(driver, label, grado, nombre_corto, ventana_desde, basal):
    datos = {'estudiante': label, 'nombre_corto': nombre_corto, 'grado': grado}
    logger.info(f"=== Revisando {label} ===")
    datos['mensajes']       = revisar_mensajes(driver, ventana_desde, basal)
    datos['calificaciones'] = revisar_calificaciones(driver, basal)
    datos['asistencia']     = revisar_asistencia(driver, basal)
    datos['boleta']         = revisar_seccion_simple(driver, 'boleta', basal,
        'Hubo cambios en la boleta de conducta? Detalla que cambio.')
    datos['anotaciones']    = revisar_seccion_simple(driver, 'anotaciones', basal,
        'Lista anotaciones nuevas con fecha, tipo, descripcion y profesor.')
    datos['aula_virtual']   = revisar_aula_virtual(driver, ventana_desde, basal)
    datos['agenda']         = revisar_agenda(driver, basal)
    return datos
