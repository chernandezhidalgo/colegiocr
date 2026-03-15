"""
wootit.py — Scraping completo del portal WootIT.
Versión 3.0.0 — Mejoras M1-M8 implementadas:
  M1+M2: Agenda estructurada evento a evento con temarios y cuenta regresiva
  M3:    Aula Virtual con extracción individual de tareas e instrucciones
  M4:    Clasificación por días restantes y nivel de urgencia
  M6:    Calificaciones completas siempre (no solo cambios)
  M7:    Asistencia con porcentaje acumulado y alerta de riesgo
  M8:    Descarga y resumen de materiales adjuntos en Aula Virtual
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
    """Días desde hoy hasta fecha_str. Retorna 999 si no parsea."""
    if not fecha_str:
        return 999
    for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y']:
        try:
            return (datetime.strptime(fecha_str.strip(), fmt).date() - date.today()).days
        except ValueError:
            pass
    return 999


def _nivel_urgencia(tipo, dias):
    """Urgencia: CRITICA / ALTA / MEDIA / BAJA."""
    es_eval = any(t in tipo.lower()
                  for t in ['examen', 'prueba', 'quiz', 'evaluacion', 'test', 'parcial'])
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
    """Extrae todos los mensajes del período con cuerpo completo y adjuntos."""
    url = config.BASE_URL + SECCIONES['mensajes']
    if not wait_and_get(driver, url, 'body'):
        return [{'error': 'Seccion mensajes no disponible'}]

    soup = _soup(driver)
    filas = soup.select('tr.mensaje, tr.msg, .mensaje-fila, .message-row, li.mensaje')
    resultados = []

    for fila in filas:
        try:
            fecha_el = (fila.select_one('.fecha, .date, td:nth-child(3)') or
                        fila.select_one('td:nth-child(2)'))
            fecha_txt = fecha_el.get_text(strip=True) if fecha_el else ''

            fecha_msg = None
            for fmt in ['%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M', '%d-%m-%Y %H:%M',
                        '%d/%m/%Y', '%Y-%m-%d']:
                try:
                    fecha_msg = datetime.strptime(fecha_txt.strip(), fmt).replace(tzinfo=TZ_CR)
                    break
                except ValueError:
                    pass

            if fecha_msg and fecha_msg < ventana_desde:
                continue

            leido = _es_leido(fila)
            asunto_el = fila.select_one('.asunto, .subject, .titulo, td:nth-child(1) a')
            remitente_el = fila.select_one('.remitente, .from, .sender, td:nth-child(2)')
            asunto = asunto_el.get_text(strip=True) if asunto_el else 'Sin asunto'
            remitente = remitente_el.get_text(strip=True) if remitente_el else 'Desconocido'

            cuerpo = ''
            adjuntos_procesados = []
            link_el = fila.select_one('a[href]')
            if link_el:
                href = link_el['href']
                url_msg = config.BASE_URL + href if href.startswith('/') else href
                if wait_and_get(driver, url_msg, 'body'):
                    soup_msg = _soup(driver)
                    cuerpo_el = soup_msg.select_one(
                        '.cuerpo, .body, .mensaje-body, #contenido-mensaje')
                    cuerpo = cuerpo_el.get_text(separator='\n', strip=True) if cuerpo_el else ''

                    if len(cuerpo) < 30 and config.USAR_COMPUTER_USE:
                        cuerpo = analizar_pantalla_con_claude(driver,
                            'Lee el cuerpo completo de este mensaje educativo y transcrIbelo integro.')

                    for adj in soup_msg.select(
                        'a[href*=".pdf"], a[href*=".jpg"], a[href*=".png"], '
                        'a[href*=".jpeg"], a[href*=".gif"], a[href*=".webp"]'
                    ):
                        adj_url = (config.BASE_URL + adj['href']
                                   if adj['href'].startswith('/') else adj['href'])
                        adj_nombre = f"{asunto[:30]}_{adj['href'].split('/')[-1]}"
                        adj_datos = procesar_adjunto(adj_url, adj_nombre, _cookies(driver))
                        adjuntos_procesados.append(adj_datos)

            texto_completo = (asunto + ' ' + cuerpo).lower()
            urgencia = 'Baja'
            razon_urgencia = 'Sin palabras clave de alerta'
            palabras_alta = ['urgente', 'pago', 'suspension', 'expulsion', 'reunion',
                             'vence hoy', 'manana', 'evaluacion', 'falta']
            palabras_media = ['examen', 'tarea', 'aviso', 'recordatorio', 'fecha limite']

            for p in palabras_alta:
                if p in texto_completo:
                    urgencia = 'Alta'
                    razon_urgencia = f'Contiene "{p}"'
                    break
            if urgencia == 'Baja':
                for p in palabras_media:
                    if p in texto_completo:
                        urgencia = 'Media'
                        razon_urgencia = f'Contiene "{p}"'
                        break

            resultados.append({
                'asunto': asunto,
                'remitente': remitente,
                'fecha': fecha_txt,
                'cuerpo': cuerpo,
                'adjuntos': adjuntos_procesados,
                'urgencia': urgencia,
                'razon_urgencia': razon_urgencia,
                'estado': '[YA LEIDO]' if leido else '[NUEVO]',
            })
        except Exception as e:
            logger.warning(f'Error procesando mensaje: {e}')

    if not resultados and config.USAR_COMPUTER_USE:
        analisis = analizar_pantalla_con_claude(driver,
            'Lista todos los mensajes visibles con: asunto, remitente, fecha, '
            'estado (leido/no leido) y si hay adjuntos.')
        if analisis:
            resultados.append({'analisis_visual': analisis, 'estado': '[ANALISIS VISUAL]',
                                'urgencia': 'Media', 'razon_urgencia': 'Revision visual'})
    return resultados


# ============================================================
# CALIFICACIONES — M6: tabla completa siempre
# ============================================================

def revisar_calificaciones(driver, basal):
    """M6: Retorna SIEMPRE la tabla completa de notas con estado aprobado/reprobado."""
    url = config.BASE_URL + SECCIONES['calificaciones']
    if not wait_and_get(driver, url, 'body'):
        return [{'error': 'Seccion calificaciones no disponible'}]

    soup = _soup(driver)
    tabla = soup.select('table tr, .calificacion-row, .nota-row')
    todas_notas = []
    basal_notas = basal.get('calificaciones', {})

    for fila in tabla[1:]:
        celdas = fila.select('td')
        if len(celdas) >= 2:
            materia = celdas[0].get_text(strip=True)
            nota = celdas[1].get_text(strip=True)
            fecha = celdas[2].get_text(strip=True) if len(celdas) > 2 else ''
            if not materia:
                continue
            try:
                nota_num = float(nota.replace(',', '.'))
                estado = 'Aprobada' if nota_num >= 65 else 'REPROBADA'
            except ValueError:
                nota_num = None
                estado = ''
            nota_anterior = basal_notas.get(materia)
            cambio = (nota != nota_anterior) if nota_anterior else False
            todas_notas.append({
                'materia': materia,
                'nota': nota,
                'nota_num': nota_num,
                'nota_anterior': nota_anterior or '(sin historial)',
                'cambio': cambio,
                'estado': estado,
                'fecha': fecha,
            })

    if not todas_notas and config.USAR_COMPUTER_USE:
        analisis = analizar_pantalla_con_claude(driver,
            'Lista todas las calificaciones: materia, nota actual, estado aprobado/reprobado.')
        if analisis:
            return [{'analisis_visual': analisis}]

    return todas_notas


# ============================================================
# ASISTENCIA — M7: porcentaje acumulado + alerta de riesgo
# ============================================================

def revisar_asistencia(driver, basal):
    """M7: Extrae porcentaje acumulado y detecta riesgo si < 85 por ciento."""
    url = config.BASE_URL + SECCIONES['asistencia']
    if not wait_and_get(driver, url, 'body'):
        return {'error': 'Seccion asistencia no disponible'}

    soup = _soup(driver)
    result = {'porcentaje': None, 'total_ausencias': 0, 'riesgo': False, 'detalle': []}

    for sel in ['.porcentaje-asistencia', '.pct-asistencia', '.attendance-pct',
                'td.porcentaje', 'span.porcentaje']:
        el = soup.select_one(sel)
        if el:
            result['porcentaje'] = el.get_text(strip=True)
            try:
                pct = float(result['porcentaje'].replace('%', '').replace(',', '.'))
                result['riesgo'] = pct < 85
            except ValueError:
                pass
            break

    for fila in soup.select('table tr, .asistencia-row')[1:]:
        celdas = fila.select('td')
        if len(celdas) >= 2:
            materia = celdas[0].get_text(strip=True)
            ausencias = celdas[1].get_text(strip=True)
            pct_mat = celdas[2].get_text(strip=True) if len(celdas) > 2 else ''
            if materia:
                try:
                    result['total_ausencias'] += int(ausencias)
                except ValueError:
                    pass
                result['detalle'].append({
                    'materia': materia,
                    'ausencias': ausencias,
                    'pct': pct_mat,
                })

    if not result['detalle'] and config.USAR_COMPUTER_USE:
        analisis = analizar_pantalla_con_claude(driver,
            'Extrae el porcentaje de asistencia total y ausencias por materia. '
            'Indica si hay riesgo de perder alguna materia por faltas.')
        result['analisis_visual'] = analisis

    return result


# ============================================================
# SECCION SIMPLE (boleta, anotaciones)
# ============================================================

def revisar_seccion_simple(driver, seccion_key, basal, pregunta_claude):
    url = config.BASE_URL + SECCIONES[seccion_key]
    if not wait_and_get(driver, url, 'body'):
        return [{'error': f'Seccion {seccion_key} no disponible'}]

    soup = _soup(driver)
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
# AULA VIRTUAL — M3+M8: tareas individuales + materiales
# ============================================================

def _extraer_detalle_tarea(driver, url_tarea, url_lista):
    """M3+M8: Abre una tarea y extrae instrucciones y materiales adjuntos."""
    if not wait_and_get(driver, url_tarea, 'body'):
        return {}
    soup = _soup(driver)
    instrucciones = ''
    for sel in ['.instrucciones', '.description', '.tarea-body',
                '#tarea-contenido', '.assignment-description', '.contenido']:
        el = soup.select_one(sel)
        if el:
            instrucciones = el.get_text(separator='\n', strip=True)
            if len(instrucciones) > 20:
                break

    if len(instrucciones) < 30 and config.USAR_COMPUTER_USE:
        instrucciones = analizar_pantalla_con_claude(driver,
            'Describe las instrucciones completas de esta tarea escolar. '
            'Que debe hacer el estudiante? Cual es el formato de entrega? '
            'Hay criterios de evaluacion o rubrica?')

    adjuntos = []
    for adj in soup.select('a[href*=".pdf"], a[href*=".docx"], a[href*=".doc"], '
                            'a[href*=".pptx"], a[href*=".xlsx"]'):
        adj_url = (config.BASE_URL + adj['href']
                   if adj['href'].startswith('/') else adj['href'])
        nombre = adj.get_text(strip=True) or adj['href'].split('/')[-1]
        adjuntos.append({'nombre': nombre, 'url': adj_url})

    wait_and_get(driver, url_lista, 'body')
    return {'instrucciones': instrucciones[:600], 'adjuntos': adjuntos}


def revisar_aula_virtual(driver, ventana_desde, basal):
    """M3+M8: Extrae cada tarea individualmente con instrucciones y materiales."""
    url = config.BASE_URL + SECCIONES['aula_virtual']
    if not wait_and_get(driver, url, 'body'):
        return {'error': 'Seccion aula virtual no disponible'}

    soup = _soup(driver)
    tareas = []

    for sel_tarea in ['.tarea-item', '.assignment-item', '.task-item',
                       '.por-entregar .tarea', 'li.tarea', 'tr.tarea']:
        items_html = soup.select(sel_tarea)
        if items_html:
            for item in items_html[:8]:
                nombre_el = item.select_one('.nombre, .title, .tarea-nombre, a')
                fecha_el = item.select_one('.fecha, .due-date, .vencimiento, .fecha-limite')
                materia_el = item.select_one('.materia, .subject, .curso, .asignatura')
                link_el = item.select_one('a[href]')

                nombre = nombre_el.get_text(strip=True) if nombre_el else 'Sin nombre'
                fecha = fecha_el.get_text(strip=True) if fecha_el else ''
                materia = materia_el.get_text(strip=True) if materia_el else ''
                dias = _dias_hasta(fecha)

                detalle = {}
                if link_el and link_el.get('href'):
                    href = link_el['href']
                    url_t = config.BASE_URL + href if href.startswith('/') else href
                    detalle = _extraer_detalle_tarea(driver, url_t, url)

                tareas.append({
                    'nombre': nombre,
                    'materia': materia,
                    'fecha_limite': fecha,
                    'dias_restantes': dias,
                    'estado': 'atrasada' if dias < 0 else 'pendiente',
                    'instrucciones': detalle.get('instrucciones', ''),
                    'materiales': detalle.get('adjuntos', []),
                })
            break

    if not tareas and config.USAR_COMPUTER_USE:
        analisis = analizar_pantalla_con_claude(driver,
            'Lista todas las tareas en Por Entregar. '
            'Para cada una: nombre exacto, materia, fecha limite e instrucciones breves.')
        tareas = [{'analisis_visual': analisis}] if analisis else []

    atrasadas = len([t for t in tareas
                     if isinstance(t, dict) and t.get('estado') == 'atrasada'])
    return {
        'tareas': tareas,
        'total_pendientes': len(tareas),
        'total_atrasadas': atrasadas,
    }


# ============================================================
# AGENDA — M1+M2+M4: estructurada con temarios y cuenta regresiva
# ============================================================

def _extraer_temario_evento(driver, url_evento, url_agenda):
    """M1: Abre detalle de un evento y extrae temario. Fallback a Claude Vision."""
    if not url_evento or not wait_and_get(driver, url_evento, 'body'):
        return []
    soup = _soup(driver)
    temario = []

    for sel in ['.temario li', '.objetivos li', '.contenido li',
                '.event-description li', 'ul.temas li', '#evento-detalle li']:
        items = soup.select(sel)
        if items:
            temario = [i.get_text(strip=True) for i in items if i.get_text(strip=True)]
            break

    if not temario:
        for sel in ['.event-description', '.descripcion', '.contenido',
                    '#evento-detalle', '.temario', '.evaluacion-descripcion']:
            el = soup.select_one(sel)
            if el:
                texto = el.get_text(separator='\n', strip=True)
                if len(texto) > 20:
                    temario = [l.strip() for l in texto.splitlines()
                               if len(l.strip()) > 3]
                    break

    if not temario and config.USAR_COMPUTER_USE:
        analisis = analizar_pantalla_con_claude(driver,
            'Extrae el temario completo de esta evaluacion escolar. '
            'Lista CADA tema, topico u objetivo en una linea separada. '
            'Incluye: temas de estudio, paginas del libro si las hay, '
            'objetivos de aprendizaje. Responde SOLO con la lista numerada, '
            'sin encabezados adicionales.')
        if analisis:
            temario = [l.strip() for l in analisis.splitlines()
                       if l.strip() and len(l.strip()) > 3]

    wait_and_get(driver, url_agenda, 'body')
    return temario[:25]


def revisar_agenda(driver, basal):
    """
    M1+M2+M4: Extrae eventos estructurados individualmente.
    Cada evento incluye: titulo, materia, tipo, fecha, dias_restantes,
    urgencia, temario (lista de temas).
    """
    url = config.BASE_URL + SECCIONES['agenda']
    if not wait_and_get(driver, url, 'body'):
        return [{'error': 'Seccion agenda no disponible'}]

    soup = _soup(driver)
    eventos_raw = []

    for sel in ['.fc-event', '.fc-daygrid-event', '.fc-timegrid-event',
                '.calendar-event', '.evento-item', 'a.event-link', '.event']:
        elementos = soup.select(sel)
        if elementos:
            for el in elementos:
                texto = el.get_text(separator=' ', strip=True)
                href = el.get('href', '')
                fecha = (el.get('data-date') or el.get('data-start') or
                         el.get('data-evento-fecha') or '')
                # Buscar fecha en elemento padre si no esta en el propio
                if not fecha:
                    padre = el.find_parent(attrs={'data-date': True})
                    if padre:
                        fecha = padre.get('data-date', '')
                if texto and len(texto) > 2:
                    eventos_raw.append({'texto': texto, 'href': href, 'fecha_raw': fecha})
            if eventos_raw:
                break

    # Si HTML no dio resultados: Claude Vision con JSON
    if not eventos_raw:
        if not config.USAR_COMPUTER_USE:
            return [{'error': 'No se detectaron eventos (Computer Use desactivado)'}]
        analisis_vis = analizar_pantalla_con_claude(driver,
            'Lista TODOS los eventos del calendario visibles. '
            'Para cada evento responde UNICAMENTE con este JSON (sin markdown): '
            '[{"titulo":"","fecha":"dd/mm/yyyy","tipo":"examen|quiz|prueba|tarea|actividad|feriado","materia":""}] '
            'Si no hay eventos responde: []')
        if not analisis_vis:
            return [{'error': 'Agenda vacia o no disponible'}]
        try:
            txt = re.sub(r'```[a-z]*', '', analisis_vis).strip().strip('`').strip()
            evs = json.loads(txt)
            if not isinstance(evs, list):
                raise ValueError('no es lista')
            procesados = []
            for ev in evs:
                dias = _dias_hasta(ev.get('fecha', ''))
                tipo = ev.get('tipo', 'actividad')
                procesados.append({
                    'titulo': ev.get('titulo', ''),
                    'materia': ev.get('materia', ''),
                    'tipo': tipo,
                    'fecha': ev.get('fecha', ''),
                    'dias_restantes': dias,
                    'urgencia': _nivel_urgencia(tipo, dias),
                    'temario': [],
                })
            procesados.sort(key=lambda x: (
                {'CRITICA': 0, 'ALTA': 1, 'MEDIA': 2, 'BAJA': 3}.get(x['urgencia'], 4),
                x['dias_restantes']))
            return procesados
        except (json.JSONDecodeError, ValueError):
            return [{'analisis_visual': analisis_vis, 'tipo': 'agenda_detallada'}]

    # Procesar cada evento con extraccion de temario
    procesados = []
    for ev in eventos_raw[:12]:
        titulo = ev['texto']
        fecha_str = ev.get('fecha_raw', '')
        dias = _dias_hasta(fecha_str)
        titulo_lower = titulo.lower()

        if any(t in titulo_lower for t in ['examen', 'parcial']):
            tipo = 'examen'
        elif 'quiz' in titulo_lower:
            tipo = 'quiz'
        elif 'prueba' in titulo_lower:
            tipo = 'prueba'
        elif any(t in titulo_lower for t in ['tarea', 'trabajo', 'proyecto', 'entrega']):
            tipo = 'tarea'
        elif any(t in titulo_lower for t in ['feriado', 'asueto', 'libre', 'no hay clase']):
            tipo = 'feriado'
        else:
            tipo = 'actividad'

        materia = titulo
        for pt in ['quiz', 'examen', 'prueba', 'tarea', 'trabajo', 'proyecto', 'parcial']:
            materia = materia.lower().replace(pt, '').strip().title()

        urgencia = _nivel_urgencia(tipo, dias)
        temario = []
        if tipo in ('examen', 'quiz', 'prueba', 'tarea') and ev.get('href'):
            href = ev['href']
            url_det = config.BASE_URL + href if href.startswith('/') else href
            temario = _extraer_temario_evento(driver, url_det, url)

        procesados.append({
            'titulo': titulo,
            'materia': materia,
            'tipo': tipo,
            'fecha': fecha_str,
            'dias_restantes': dias,
            'urgencia': urgencia,
            'temario': temario,
        })

    procesados.sort(key=lambda x: (
        {'CRITICA': 0, 'ALTA': 1, 'MEDIA': 2, 'BAJA': 3}.get(x['urgencia'], 4),
        x['dias_restantes']))
    return procesados


# ============================================================
# ORQUESTADOR PRINCIPAL
# ============================================================

def revisar_estudiante(driver, label, grado, nombre_corto, ventana_desde, basal):
    """Ejecuta la revision completa de todas las secciones para un estudiante."""
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
