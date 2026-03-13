"""Módulo principal de scraping de Woot It.
Combina Selenium (estructurado) + Claude Computer Use (visual).
"""import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import config
from modules.attachments import procesar_adjunto
from modules.browser import analizar_pantalla_con_claude, wait_and_get

TZ_CR = ZoneInfo('America/Costa_Rica')
logger = logging.getLogger(__name__)

SECCIONES = {
    'mensajes': '/comunicacion/mensajes/recibidos.cfm',
    'calificaciones': '/calificaciones/estudiante.cfm',
    'asistencia': '/asistenciayconductaEst/index.cfm?sec=asistencia',
    'boleta': '/asistenciayconductaEst/index.cfm?sec=boletas',
    'anotaciones': '/asistenciayconductaEst/index.cfm?sec=anotaciones',
    'aula_virtual': '/aulavirtual/',
    'agenda': '/v3/calendar/home/index.cfm',
}


def _soup(driver) -> BeautifulSoup:
    return BeautifulSoup(driver.page_source, 'lxml')


def _cookies(driver) -> dict:
    return {c['name']: c['value'] for c in driver.get_cookies()}


def _es_leido(elemento) -> bool:
    """Detecta si un mensaje ya fue leído por el padre."""
    clases = elemento.get('class', [])
    return any(c in ['leido', 'read', 'opened'] for c in clases)


def cargar_basal(estudiante_key: str) -> dict:
    ruta = Path(config.DIR_BASAL) / f"basal_{estudiante_key}.json"
    if ruta.exists():
        return json.loads(ruta.read_text(encoding='utf-8'))
    return {}


def guardar_basal(estudiante_key: str, datos: dict):
    ruta = Path(config.DIR_BASAL) / f"basal_{estudiante_key}.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding='utf-8')


def revisar_mensajes(driver, ventana_desde: datetime, basal: dict) -> list:
    url = config.BASE_URL + SECCIONES['mensajes']
    if not wait_and_get(driver, url, 'body'):
        return [{'error': 'Sección mensajes no disponible'}]
    
    soup = _soup(driver)
    filas = soup.select('tr.mensaje, tr.msg, .mensaje-fila, .message-row, li.mensaje')
    resultados = []
    
    for fila in filas:
        try:
            fecha_txt = (fila.select_one('.fecha, .date, td:nth-child(3)') or
                         fila.select_one('td:nth-child(2)')).get_text(strip=True)
            
            for fmt in ['%d/%m/%Y %H:%M', '%Y-%m-%d %H:%M', '%d-%m-%Y %H:%M',
                        '%d/%m/%Y', '%Y-%m-%d']:
                try:
                    fecha_msg = datetime.strptime(fecha_txt.strip(), fmt).replace(tzinfo=TZ_CR)
                    break
                except ValueError:
                    fecha_msg = None
            
            if fecha_msg and fecha_msg < ventana_desde:
                continue
                
            leido = _es_leido(fila)
            asunto_el = fila.select_one('.asunto, .subject, .titulo, td:nth-child(1) a')
            asunto = asunto_el.get_text(strip=True) if asunto_el else 'Sin asunto'
            remitente_el = fila.select_one('.remitente, .from, .sender, td:nth-child(2)')
            remitente = remitente_el.get_text(strip=True) if remitente_el else 'Desconocido'
            
            cuerpo = ''
            adjuntos_procesados = []
            link_el = fila.select_one('a[href]')
            if link_el:
                href = link_el['href']
                url_msg = config.BASE_URL + href if href.startswith('/') else href
                if wait_and_get(driver, url_msg, 'body'):
                    soup_msg = _soup(driver)
                    cuerpo_el = soup_msg.select_one('.cuerpo, .body, .mensaje-body, #contenido-mensaje')
                    cuerpo = cuerpo_el.get_text(separator='\
', strip=True) if cuerpo_el else ''
                    
                    if len(cuerpo) < 30:
                        cuerpo = analizar_pantalla_con_claude(driver,
                            'Lee el cuerpo completo de este mensaje educativo y transcríbelo íntegro.')
                    
                    for adj in soup_msg.select('a[href*=\".pdf\"], a[href*=\".jpg\"], a[href*=\".png\"], ' +
                                             'a[href*=\".jpeg\"], a[href*=\".gif\"], a[href*=\".webp\"]'):
                        adj_url = config.BASE_URL + adj['href'] if adj['href'].startswith('/') else adj['href']
                        adj_nombre = f\"{asunto[:30]}_{adj['href'].split('/')[-1]}\"
                        adj_datos = procesar_adjunto(adj_url, adj_nombre, _cookies(driver))
                        adjuntos_procesados.append(adj_datos)
            
            texto_completo = (asunto + ' ' + cuerpo).lower()
            urgencia = 'Baja'
            razon_urgencia = 'Sin palabras clave de alerta'
            palabras_alta = ['urgente', 'pago', 'suspensión', 'expulsión', 'reunión',
                           'vence hoy', 'mañana', 'evaluación', 'falta']
            palabras_media = ['examen', 'tarea', 'aviso', 'recordatorio', 'fecha límite']
            
            for p in palabras_alta:
                if p in texto_completo:
                    urgencia = 'Alta'
                    razon_urgencia = f'Contiene \"{p}\"'
                    break
            
            if urgencia == 'Baja':
                for p in palabras_media:
                    if p in texto_completo:
                        urgencia = 'Media'
                        razon_urgencia = f'Contiene \"{p}\"'
                        break
            
            resultados.append({
                'asunto': asunto,
                'remitente': remitente,
                'fecha': fecha_txt,
                'cuerpo': cuerpo,
                'adjuntos': adjuntos_procesados,
                'urgencia': urgencia,
                'razon_urgencia': razon_urgencia,
                'estado': '[YA LEÍDO POR EL PADRE]' if leido else '[NUEVO]',
            })
        except Exception as e:
            logger.warning(f\"Error procesando mensaje: {e}\")
            
    if not resultados:
        analisis = analizar_pantalla_con_claude(driver,
            'Lista todos los mensajes visibles con: asunto, remitente, fecha, ' +
            'estado (leído/no leído) y si hay adjuntos.')
        if analisis:
            resultados.append({'analisis_visual': analisis, 'estado': '[ANÁLISIS VISUAL]',
                             'urgencia': 'Media', 'razon_urgencia': 'Revisión visual automática'})
    return resultados


def revisar_calificaciones(driver, basal: dict) -> list:
    url = config.BASE_URL + SECCIONES['calificaciones']
    if not wait_and_get(driver, url, 'body'):
        return [{'error': 'Sección calificaciones no disponible'}]
    
    soup = _soup(driver)
    tabla = soup.select('table tr, .calificacion-row, .nota-row')
    cambios = []
    basal_notas = basal.get('calificaciones', {})
    
    for fila in tabla[1:]:
        celdas = fila.select('td')
        if len(celdas) >= 2:
            materia = celdas[0].get_text(strip=True)
            nota = celdas[1].get_text(strip=True)
            fecha = celdas[2].get_text(strip=True) if len(celdas) > 2 else ''
            nota_anterior = basal_notas.get(materia)
            if nota != nota_anterior:
                cambios.append({
                    'materia': materia,
                    'nota_anterior': nota_anterior or '(sin basal)',
                    'nota_nueva': nota,
                    'fecha': fecha
                })
    
    if not cambios and not tabla:
        analisis = analizar_pantalla_con_claude(driver,
            'Lista todas las calificaciones visibles con materia, nota y fecha.')
        if analisis:
            cambios.append({'analisis_visual': analisis})
    return cambios


def revisar_seccion_simple(driver, seccion_key: str, basal: dict, pregunta_claude: str) -> list:
    url = config.BASE_URL + SECCIONES[seccion_key]
    if not wait_and_get(driver, url, 'body'):
        return [{'error': f'Sección {seccion_key} no disponible'}]
    
    soup = _soup(driver)
    filas = soup.select('table tr, .fila, .row-item, li')
    items = []
    for fila in filas[1:]:
        texto = fila.get_text(separator=' | ', strip=True)
        if texto:
            items.append({'detalle': texto})
    
    if not items:
        analisis = analizar_pantalla_con_claude(driver, pregunta_claude)
        if analisis:
            items.append({'analisis_visual': analisis})
    return items


def revisar_aula_virtual(driver, ventana_desde: datetime, basal: dict) -> dict:
    url = config.BASE_URL + SECCIONES['aula_virtual']
    if not wait_and_get(driver, url, 'body'):
        return {'error': 'Sección aula virtual no disponible'}
    
    analisis = analizar_pantalla_con_claude(driver,
        'Lista: (1) Tareas en \"Por Entregar\" con nombre, materia y fecha límite. ' +
        '(2) Posts nuevos con título, materia y fecha. ' +
        '(3) Videoconferencias próximas con fecha, hora, materia y enlace.')
    
    soup = _soup(driver)
    tareas_el = soup.select('.tarea, .task, .por-entregar, .assignment')
    tareas = [{'detalle': t.get_text(separator=' ', strip=True)} for t in tareas_el]
    return {
        'tareas': tareas or [{'analisis_visual': analisis}],
        'analisis_completo': analisis
    }


def revisar_agenda(driver, basal: dict) -> list:
    """
    Extrae eventos de la agenda con foco especial en pruebas y quizzes.
    Utiliza Computer Use para obtener el temario detallado de cada prueba.
    """
    url = config.BASE_URL + SECCIONES['agenda']
    if not wait_and_get(driver, url, 'body'):
        return [{'error': 'Sección agenda no disponible'}]
    
    # Análisis detallado enfocado en pruebas/temarios
    pregunta = (
        \"Analiza el calendario de los próximos 15 días. Identifica específicamente \"
        \"EXÁMENES, PRUEBAS, QUIZZES o EVALUACIONES. \"
        \"Para cada una, extrae: 1) Fecha exacta, 2) Materia, 3) Título del examen/quiz, \"
        \"4) TEMARIO DETALLADO (temas a estudiar, páginas, objetivos) y 5) Materiales. \"
        \"Si no hay pruebas, lista los eventos generales con su descripción.\"
    )
    
    analisis = analizar_pantalla_con_claude(driver, pregunta)
    
    soup = _soup(driver)
    eventos_el = soup.select('.event, .evento, .calendar-event, .fc-event')
    eventos = []
    
    for e in eventos_el:
        texto = e.get_text(separator=' | ', strip=True)
        if texto:
            eventos.append({'detalle': texto})
            
    # Retornar estructura que prioriza el análisis visual detallado si existe
    if analisis:
        return [{'analisis_visual': analisis, 'tipo': 'agenda_detallada'}]
    return eventos or [{'error': 'No se detectaron eventos en la agenda'}]


def revisar_estudiante(driver, label: str, grado: str, nombre_corto: str,
                      ventana_desde: datetime, basal: dict) -> dict:
    datos = {'estudiante': label, 'nombre_corto': nombre_corto, 'grado': grado}
    logger.info(f\"=== Revisando {label} ===\")
    
    datos['mensajes'] = revisar_mensajes(driver, ventana_desde, basal)
    datos['calificaciones'] = revisar_calificaciones(driver, basal)
    datos['asistencia'] = revisar_seccion_simple(driver, 'asistencia', basal,
        'Lista ausencias y tardías registradas hoy con fecha, tipo y materia.')
    datos['boleta'] = revisar_seccion_simple(driver, 'boleta', basal,
        '¿Hubo cambios en la boleta de conducta o disciplina? Detalla qué cambió.')
    datos['anotaciones'] = revisar_seccion_simple(driver, 'anotaciones', basal,
        'Lista anotaciones nuevas con fecha, tipo, descripción y profesor.')
    datos['aula_virtual'] = revisar_aula_virtual(driver, ventana_desde, basal)
    datos['agenda'] = revisar_agenda(driver, basal)
    
    return datos
