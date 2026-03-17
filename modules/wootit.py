"""
wootit.py v5.0.0 — Extracción de datos WootIT vía API HTTP directa.

SIN PLAYWRIGHT, SIN SELENIUM, SIN CHROMEDRIVER.

Arquitectura:
  - Endpoints JSON (Lucee CFC): agenda, aula virtual
  - Endpoints HTML (server-side): calificaciones, mensajes, asistencia,
    boleta, anotaciones → BeautifulSoup parsing

El parámetro 'driver' en las firmas públicas es ahora un WootITClient.
Se mantiene el nombre 'driver' para no romper las llamadas desde basal.py
y revision_matutina.py.
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
from modules.api_client import WootITClient

TZ_CR  = ZoneInfo("America/Costa_Rica")
logger = logging.getLogger(__name__)


# ── Utilidades de fecha / urgencia ────────────────────────────────────────────

def _dias_hasta(fecha_str) -> int:
    if not fecha_str:
        return 999
    # Intentar timestamp epoch ms (formato Lucee)
    if isinstance(fecha_str, (int, float)):
        try:
            d = datetime.fromtimestamp(fecha_str / 1000, tz=TZ_CR).date()
            return (d - date.today()).days
        except Exception:
            return 999
    for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S"]:
        try:
            return (datetime.strptime(str(fecha_str).strip()[:10], fmt).date()
                    - date.today()).days
        except ValueError:
            pass
    return 999


def _nivel_urgencia(tipo: str, dias: int) -> str:
    es_eval = any(t in tipo.lower()
                  for t in ["examen", "prueba", "quiz", "evaluacion", "test", "parcial"])
    if es_eval:
        if dias <= 2:  return "CRITICA"
        if dias <= 5:  return "ALTA"
        if dias <= 10: return "MEDIA"
        return "BAJA"
    else:
        if dias <= 0:  return "ALTA"
        if dias <= 3:  return "MEDIA"
        return "BAJA"


def _es_leido(el) -> bool:
    return any(c in el.get("class", []) for c in ["leido", "read", "opened"])


# ── Basal persistence ─────────────────────────────────────────────────────────

def cargar_basal(key: str) -> dict:
    ruta = Path(config.DIR_BASAL) / f"basal_{key}.json"
    if ruta.exists():
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def guardar_basal(key: str, datos: dict):
    Path(config.DIR_BASAL).mkdir(parents=True, exist_ok=True)
    (Path(config.DIR_BASAL) / f"basal_{key}.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── MENSAJES (HTML scraping) ──────────────────────────────────────────────────

def revisar_mensajes(driver: WootITClient, ventana_desde, basal: dict) -> list:
    soup = driver.get_mensajes_html()
    filas = soup.select("tr.mensaje, tr.msg, .mensaje-fila, .message-row, li.mensaje")
    resultados = []

    for fila in filas:
        try:
            fecha_el  = (fila.select_one(".fecha, .date, td:nth-child(3)")
                         or fila.select_one("td:nth-child(2)"))
            fecha_txt = fecha_el.get_text(strip=True) if fecha_el else ""
            fecha_msg = None
            for fmt in ["%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y", "%Y-%m-%d"]:
                try:
                    fecha_msg = datetime.strptime(
                        fecha_txt.strip(), fmt).replace(tzinfo=TZ_CR)
                    break
                except ValueError:
                    pass
            if fecha_msg and fecha_msg < ventana_desde:
                continue

            leido        = _es_leido(fila)
            asunto_el    = fila.select_one(".asunto, .subject, .titulo, td:nth-child(1) a")
            remitente_el = fila.select_one(".remitente, .from, .sender, td:nth-child(2)")
            asunto    = asunto_el.get_text(strip=True)    if asunto_el    else "Sin asunto"
            remitente = remitente_el.get_text(strip=True) if remitente_el else "Desconocido"

            tc = asunto.lower()
            urg, razon = "Baja", "Sin palabras clave"
            for p in ["urgente", "pago", "suspension", "reunion", "evaluacion", "falta"]:
                if p in tc:
                    urg, razon = "Alta", f'Contiene "{p}"'; break
            if urg == "Baja":
                for p in ["examen", "tarea", "aviso", "recordatorio"]:
                    if p in tc:
                        urg, razon = "Media", f'Contiene "{p}"'; break

            resultados.append({
                "asunto": asunto, "remitente": remitente, "fecha": fecha_txt,
                "cuerpo": "", "adjuntos": [],
                "urgencia": urg, "razon_urgencia": razon,
                "estado": "[YA LEIDO]" if leido else "[NUEVO]",
            })
        except Exception as e:
            logger.warning(f"Error mensaje: {e}")

    logger.info(f"Mensajes extraídos: {len(resultados)}")
    return resultados


# ── CALIFICACIONES (HTML scraping) ────────────────────────────────────────────

def revisar_calificaciones(driver: WootITClient, basal: dict) -> list:
    soup        = driver.get_calificaciones_html()
    notas       = []
    basal_notas = basal.get("calificaciones", {})

    for selector in ["table.calificaciones tr", "table tr",
                     ".calificacion-row", ".nota-row", "tr"]:
        filas = soup.select(selector)
        if len(filas) > 1:
            for fila in filas[1:]:
                celdas = fila.select("td")
                if len(celdas) >= 2:
                    materia = celdas[0].get_text(strip=True)
                    nota    = celdas[1].get_text(strip=True)
                    fecha   = celdas[2].get_text(strip=True) if len(celdas) > 2 else ""
                    if materia and nota and len(materia) > 1 and len(nota) < 20:
                        try:
                            nn  = float(nota.replace(",", "."))
                            est = "Aprobada" if nn >= 65 else "REPROBADA"
                        except ValueError:
                            nn, est = None, ""
                        notas.append({
                            "materia": materia, "nota": nota, "nota_num": nn,
                            "nota_anterior": basal_notas.get(materia, "(sin historial)"),
                            "cambio": nota != basal_notas.get(materia),
                            "estado": est, "fecha": fecha,
                        })
            if notas:
                break

    logger.info(f"Calificaciones extraídas: {len(notas)} materias")
    return notas


# ── ASISTENCIA (HTML scraping) ────────────────────────────────────────────────

def revisar_asistencia(driver: WootITClient, basal: dict) -> dict:
    soup   = driver.get_asistencia_html()
    result = {"porcentaje": None, "total_ausencias": 0, "riesgo": False, "detalle": []}

    for sel in [".porcentaje-asistencia", ".pct-asistencia", "td.porcentaje",
                "span.porcentaje", "strong", "b"]:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(strip=True)
            if "%" in txt:
                result["porcentaje"] = txt
                try:
                    pct = float(txt.replace("%", "").replace(",", ".").strip())
                    result["riesgo"] = pct < 85
                except ValueError:
                    pass
                break

    for fila in soup.select("table tr, .asistencia-row")[1:]:
        celdas = fila.select("td")
        if len(celdas) >= 2:
            m = celdas[0].get_text(strip=True)
            a = celdas[1].get_text(strip=True)
            p = celdas[2].get_text(strip=True) if len(celdas) > 2 else ""
            if m and len(m) > 1:
                try:
                    result["total_ausencias"] += int(a)
                except ValueError:
                    pass
                result["detalle"].append({"materia": m, "ausencias": a, "pct": p})

    logger.info(f"Asistencia: {result['porcentaje']} | ausencias: {result['total_ausencias']}")
    return result


# ── BOLETA / ANOTACIONES (HTML scraping) ─────────────────────────────────────

def revisar_seccion_simple(driver: WootITClient, seccion_key: str,
                           basal: dict, pregunta_claude: str) -> list:
    if seccion_key == "boleta":
        soup = driver.get_boleta_html()
    elif seccion_key == "anotaciones":
        soup = driver.get_anotaciones_html()
    else:
        return [{"error": f"Sección {seccion_key} no implementada en API directa"}]

    items = []
    for fila in soup.select("table tr, .fila, .row-item, li")[1:]:
        txt = fila.get_text(separator=" | ", strip=True)
        if txt and len(txt) > 3:
            items.append({"detalle": txt})
    return items


# ── AULA VIRTUAL (API JSON) ───────────────────────────────────────────────────

def revisar_aula_virtual(driver: WootITClient, ventana_desde, basal: dict) -> dict:
    tareas = []

    # Tareas por entregar
    raw_entregar = driver.get_posts_aula_virtual(filtro="porentregar")
    posts_entregar = WootITClient.query_to_dicts(raw_entregar.get("MAIN", {}))
    if not posts_entregar:
        # Intentar QSHOW como fallback
        posts_entregar = WootITClient.query_to_dicts(raw_entregar.get("QSHOW", {}))

    for post in posts_entregar[:15]:
        nombre   = post.get("TITULO", "Sin nombre")
        materia  = post.get("CURSONOMBRE", "")
        fecha    = post.get("FECHA_ENTREGA") or post.get("FECHA") or ""
        id_post  = post.get("ID") or post.get("IDPOST")
        dias     = _dias_hasta(fecha)

        instrucciones = ""
        if id_post:
            det = driver.get_post_detalle(int(id_post))
            instrucciones = (det.get("DESCRIPCION") or det.get("CUERPO") or "")[:600]

        tareas.append({
            "nombre":        nombre,
            "materia":       materia,
            "fecha_limite":  str(fecha),
            "dias_restantes": dias,
            "estado":        "atrasada" if dias < 0 else "pendiente",
            "instrucciones": instrucciones,
            "materiales":    [],
        })

    # Si no hay "por entregar", traer todos
    if not tareas:
        raw_todos = driver.get_posts_aula_virtual(filtro="todos")
        posts_todos = WootITClient.query_to_dicts(raw_todos.get("MAIN", {}))
        if not posts_todos:
            posts_todos = WootITClient.query_to_dicts(raw_todos.get("QSHOW", {}))
        for post in posts_todos[:10]:
            nombre  = post.get("TITULO", "Sin nombre")
            materia = post.get("CURSONOMBRE", "")
            fecha   = post.get("FECHA_ENTREGA") or post.get("FECHA") or ""
            dias    = _dias_hasta(fecha)
            tareas.append({
                "nombre": nombre, "materia": materia,
                "fecha_limite": str(fecha), "dias_restantes": dias,
                "estado": "atrasada" if dias < 0 else "pendiente",
                "instrucciones": "", "materiales": [],
            })

    atrasadas = len([t for t in tareas if t.get("estado") == "atrasada"])
    logger.info(f"Aula virtual: {len(tareas)} tareas, {atrasadas} atrasadas")
    return {"tareas": tareas, "total_pendientes": len(tareas), "total_atrasadas": atrasadas}


# ── AGENDA (API JSON) ─────────────────────────────────────────────────────────

def revisar_agenda(driver: WootITClient, basal: dict) -> list:
    raw = driver.get_proximos_eventos()
    procesados = []

    # EVENTOSAV = tareas/evaluaciones del aula virtual
    eventos_av = WootITClient.query_to_dicts(raw.get("EVENTOSAV", {}))
    for ev in eventos_av:
        titulo  = ev.get("TITULO", "")
        materia = ev.get("CURSONOMBRE", "")
        fecha   = ev.get("FECHA") or ev.get("FECHAENTREGA") or ""
        dias    = _dias_hasta(fecha)
        tl      = titulo.lower()
        if any(t in tl for t in ["examen", "parcial"]):     tipo = "examen"
        elif "quiz" in tl:                                   tipo = "quiz"
        elif "prueba" in tl:                                 tipo = "prueba"
        elif any(t in tl for t in ["tarea", "entrega"]):    tipo = "tarea"
        else:                                                tipo = "actividad"
        procesados.append({
            "titulo": titulo, "materia": materia, "tipo": tipo,
            "fecha": str(fecha), "dias_restantes": dias,
            "urgencia": _nivel_urgencia(tipo, dias), "temario": [],
        })

    # EVENTOS = eventos del calendario institucional
    eventos_cal = WootITClient.query_to_dicts(raw.get("EVENTOS", {}))
    for ev in eventos_cal:
        titulo  = ev.get("TITULO", "")
        materia = ev.get("CURSONOMBRE", "") or ev.get("MATERIA", "")
        fecha   = ev.get("FECHA") or ""
        dias    = _dias_hasta(fecha)
        tl      = titulo.lower()
        if any(t in tl for t in ["examen", "parcial"]):     tipo = "examen"
        elif "quiz" in tl:                                   tipo = "quiz"
        elif "prueba" in tl:                                 tipo = "prueba"
        elif any(t in tl for t in ["feriado", "asueto"]):   tipo = "feriado"
        else:                                                tipo = "actividad"
        procesados.append({
            "titulo": titulo, "materia": materia, "tipo": tipo,
            "fecha": str(fecha), "dias_restantes": dias,
            "urgencia": _nivel_urgencia(tipo, dias), "temario": [],
        })

    procesados.sort(key=lambda x: (
        {"CRITICA": 0, "ALTA": 1, "MEDIA": 2, "BAJA": 3}.get(x["urgencia"], 4),
        x["dias_restantes"]
    ))

    logger.info(f"Agenda: {len(procesados)} eventos ({len(eventos_av)} AV + {len(eventos_cal)} cal)")
    return procesados if procesados else [{"info": "Sin eventos próximos detectados"}]


# ── ORQUESTADOR ───────────────────────────────────────────────────────────────

def revisar_estudiante(driver: WootITClient, label, grado,
                       nombre_corto, ventana_desde, basal) -> dict:
    datos = {"estudiante": label, "nombre_corto": nombre_corto, "grado": grado}
    logger.info(f"=== Revisando {label} ===")
    datos["mensajes"]       = revisar_mensajes(driver, ventana_desde, basal)
    datos["calificaciones"] = revisar_calificaciones(driver, basal)
    datos["asistencia"]     = revisar_asistencia(driver, basal)
    datos["boleta"]         = revisar_seccion_simple(driver, "boleta", basal, "")
    datos["anotaciones"]    = revisar_seccion_simple(driver, "anotaciones", basal, "")
    datos["aula_virtual"]   = revisar_aula_virtual(driver, ventana_desde, basal)
    datos["agenda"]         = revisar_agenda(driver, basal)
    return datos
