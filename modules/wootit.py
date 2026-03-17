"""
wootit.py v5.1.0 — Extracción datos WootIT vía API HTTP + diagnóstico HTML.

Cambios v5.1.0:
  - Intenta calificaciones via CFC antes de HTML scraping
  - Log detallado del HTML para identificar selectores correctos
  - _dias_hasta maneja timestamps Lucee (epoch ms y strings fecha)
  - Agenda: parseo robusto de fechas timestamp
"""
import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

import config
from modules.api_client import WootITClient

TZ_CR  = ZoneInfo("America/Costa_Rica")
logger = logging.getLogger(__name__)


# ── Utilidades ────────────────────────────────────────────────────────────────

# Meses en inglés para parsear fechas WootIT ("March, 17 2026 14:51:42 -0600")
_MESES_EN = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,
    "sep":9,"oct":10,"nov":11,"dec":12,
}

def _parsear_fecha_wootit(s: str):
    """
    Parsea "March, 17 2026 14:51:42 -0600" → date object.
    También maneja "March, 17" (sin año → año actual).
    """
    try:
        # Normalizar: quitar coma, split
        s2 = s.replace(",", "").strip()
        parts = s2.split()
        # ["March", "17", "2026", "14:51:42", "-0600"]
        mes_str = parts[0].lower()
        mes = _MESES_EN.get(mes_str)
        if not mes:
            return None
        dia = int(parts[1])
        # Año puede estar en posición 2 o no estar
        anio = date.today().year
        if len(parts) >= 3 and parts[2].isdigit() and len(parts[2]) == 4:
            anio = int(parts[2])
        return date(anio, mes, dia)
    except Exception:
        return None


def _dias_hasta(fecha_val) -> int:
    if not fecha_val:
        return 999
    # Timestamp epoch ms
    if isinstance(fecha_val, (int, float)):
        try:
            d = datetime.fromtimestamp(fecha_val / 1000, tz=TZ_CR).date()
            return (d - date.today()).days
        except Exception:
            return 999
    s = str(fecha_val).strip()
    # Formato Lucee /Date(ms-offset)/
    m = re.search(r'/Date\((\d+)', s)
    if m:
        try:
            d = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=TZ_CR).date()
            return (d - date.today()).days
        except Exception:
            return 999
    # Formato WootIT: "March, 17 2026 ..."
    if any(mes in s.lower() for mes in _MESES_EN):
        d = _parsear_fecha_wootit(s)
        if d:
            return (d - date.today()).days
    # Formatos ISO estándar
    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%d/%m/%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y"]:
        try:
            return (datetime.strptime(s[:19], fmt).date() - date.today()).days
        except ValueError:
            pass
    return 999


def _fecha_legible(fecha_val) -> str:
    if not fecha_val:
        return ""
    if isinstance(fecha_val, (int, float)):
        try:
            return datetime.fromtimestamp(
                fecha_val / 1000, tz=TZ_CR).strftime("%d/%m/%Y")
        except Exception:
            return str(fecha_val)
    s = str(fecha_val).strip()
    m = re.search(r'/Date\((\d+)', s)
    if m:
        try:
            return datetime.fromtimestamp(
                int(m.group(1)) / 1000, tz=TZ_CR).strftime("%d/%m/%Y")
        except Exception:
            pass
    # Formato WootIT: "March, 17 2026 ..."
    if any(mes in s.lower() for mes in _MESES_EN):
        d = _parsear_fecha_wootit(s)
        if d:
            return d.strftime("%d/%m/%Y")
    return s[:10]


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


# ── MENSAJES ──────────────────────────────────────────────────────────────────

def revisar_mensajes(driver: WootITClient, ventana_desde, basal: dict) -> list:
    # Intentar via REST backend.wootit.com/v1/
    rows_rest = driver.get_mensajes_rest()
    if rows_rest:
        logger.info(f"Mensajes REST: {len(rows_rest)}")
        return _procesar_mensajes_json(rows_rest, ventana_desde)

    # Intentar via CFC JSON
    r = driver.get_mensajes_json()
    rows = WootITClient.query_to_dicts(r)
    if rows:
        return _procesar_mensajes_json(rows, ventana_desde)

    # Fallback HTML
    soup = driver.get_mensajes_html()
    return _procesar_mensajes_html(soup, ventana_desde)


def _procesar_mensajes_json(rows: list, ventana_desde) -> list:
    resultados = []
    for row in rows:
        asunto    = row.get("ASUNTO") or row.get("TITULO") or "Sin asunto"
        remitente = row.get("REMITENTE") or row.get("FROM") or "Desconocido"
        fecha     = _fecha_legible(row.get("FECHA") or row.get("FECHAENVIO"))
        leido     = row.get("LEIDO") or row.get("READ") or False
        tc        = asunto.lower()
        urg = "Baja"
        for p in ["urgente", "pago", "suspension", "reunion", "evaluacion"]:
            if p in tc:
                urg = "Alta"; break
        if urg == "Baja":
            for p in ["examen", "tarea", "aviso"]:
                if p in tc:
                    urg = "Media"; break
        resultados.append({
            "asunto": asunto, "remitente": remitente, "fecha": fecha,
            "cuerpo": "", "adjuntos": [], "urgencia": urg,
            "razon_urgencia": "JSON", "estado": "[YA LEIDO]" if leido else "[NUEVO]",
        })
    logger.info(f"Mensajes JSON extraídos: {len(resultados)}")
    return resultados


def _procesar_mensajes_html(soup: BeautifulSoup, ventana_desde) -> list:
    filas = soup.select("tr.mensaje, tr.msg, .mensaje-fila, .message-row, li.mensaje, tr")
    resultados = []
    for fila in filas:
        try:
            celdas = fila.select("td")
            if len(celdas) < 2:
                continue
            asunto    = celdas[0].get_text(strip=True)
            remitente = celdas[1].get_text(strip=True) if len(celdas) > 1 else ""
            fecha     = celdas[2].get_text(strip=True) if len(celdas) > 2 else ""
            if not asunto or len(asunto) < 3:
                continue
            tc  = asunto.lower()
            urg = "Baja"
            for p in ["urgente", "pago", "suspension", "reunion"]:
                if p in tc:
                    urg = "Alta"; break
            resultados.append({
                "asunto": asunto, "remitente": remitente, "fecha": fecha,
                "cuerpo": "", "adjuntos": [], "urgencia": urg,
                "razon_urgencia": "HTML", "estado": "[NUEVO]",
            })
        except Exception:
            pass
    logger.info(f"Mensajes HTML extraídos: {len(resultados)}")
    return resultados


# ── CALIFICACIONES ────────────────────────────────────────────────────────────

def revisar_calificaciones(driver: WootITClient, basal: dict) -> list:
    basal_notas = basal.get("calificaciones", {})

    # Intentar via REST backend.wootit.com/v1/
    rows_rest = driver.get_calificaciones_rest()
    if rows_rest:
        logger.info(f"Calificaciones REST: {len(rows_rest)} items")
        return _procesar_calificaciones_json(
            rows_rest if isinstance(rows_rest[0], dict) else [], basal_notas)

    # Intentar via CFC JSON
    r = driver.get_calificaciones_json()
    rows = WootITClient.query_to_dicts(r)
    if rows:
        logger.info(f"Calificaciones CFC: {len(rows)} filas")
        return _procesar_calificaciones_json(rows, basal_notas)

    # Fallback HTML scraping
    soup = driver.get_calificaciones_html()
    return _procesar_calificaciones_html(soup, basal_notas)


def _procesar_calificaciones_json(rows: list, basal_notas: dict) -> list:
    notas = []
    for row in rows:
        materia = (row.get("MATERIA") or row.get("CURSONOMBRE") or
                   row.get("NOMBRE") or row.get("ASIGNATURA") or "")
        nota    = str(row.get("NOTA") or row.get("CALIFICACION") or
                      row.get("PROMEDIO") or "")
        if not materia or not nota:
            continue
        try:
            nn  = float(nota.replace(",", "."))
            est = "Aprobada" if nn >= 65 else "REPROBADA"
        except ValueError:
            nn, est = None, ""
        notas.append({
            "materia": materia, "nota": nota, "nota_num": nn,
            "nota_anterior": basal_notas.get(materia, "(sin historial)"),
            "cambio": nota != basal_notas.get(materia),
            "estado": est, "fecha": "",
        })
    logger.info(f"Calificaciones JSON: {len(notas)} materias")
    return notas


def _procesar_calificaciones_html(soup: BeautifulSoup, basal_notas: dict) -> list:
    """
    ESTRUCTURA DEFINITIVA CONFIRMADA via DevTools + PDF:

    Un col-md-4 por TRIMESTRE. Dentro: todas las materias.
    Consola: "Trimestre → 100, 60, 60, 60, 75.83"
    PDF confirma: Conducta=100, Español=60, EE.SS.=60,
                  Habilidades para la Vida=60, Progrentis=75.83
    Las demás materias no tienen barra (sin nota aún).

    Cada materia dentro del bloque tiene:
      - texto con el nombre
      - 0 o 1 .progress con .progress-bar[aria-valuenow]
    """
    notas = []

    # Tomar el bloque del I Trimestre (primera col-md-4)
    bloques = soup.select(".col-md-4")
    if not bloques:
        bloques = soup.select(".col-sm-4, .col-lg-4")

    bloque = bloques[0] if bloques else None
    if not bloque:
        logger.warning("Calificaciones: no se encontró bloque col-md-4")
        return notas

    # Dentro del bloque, cada materia es un div/elemento que puede tener
    # texto de nombre y opcionalmente una .progress con barra
    # Recorrer hijos directos del bloque
    hijos = [h for h in bloque.children if hasattr(h, 'get_text')]
    
    nombre_actual = ""
    for hijo in hijos:
        barra = hijo.select_one(".progress-bar") if hasattr(hijo, 'select_one') else None
        texto_hijo = hijo.get_text(strip=True)
        
        if barra:
            nota = barra.get("aria-valuenow") or barra.get_text(strip=True)
            # El nombre ya debería estar en nombre_actual o en texto antes de la barra
            if not nombre_actual:
                # Intentar extraer del mismo elemento
                for child in hijo.children:
                    if hasattr(child, 'select') and child.select(".progress"):
                        continue
                    txt = child.get_text(strip=True) if hasattr(child, 'get_text') else ""
                    if txt and len(txt) > 2 and not re.match(r"^[0-9. ]+$", txt):
                        nombre_actual = txt[:80]
                        break
            if nombre_actual and nota:
                try:
                    float(str(nota))
                    _agregar_nota(notas, nombre_actual, str(nota), basal_notas)
                    logger.debug(f"  ✓ {nombre_actual} = {nota}")
                except (ValueError, TypeError):
                    pass
            nombre_actual = ""
        elif texto_hijo and len(texto_hijo) > 2 and not re.match(r"^[0-9. ]+$", texto_hijo):
            # Es un nombre de materia sin barra (sin nota aún)
            nombre_actual = texto_hijo[:80]
        else:
            nombre_actual = ""

    # Si no encontró nada con hijos directos, probar subcontenedores
    if not notas:
        for barra in bloque.select(".progress-bar"):
            nota = barra.get("aria-valuenow") or barra.get_text(strip=True)
            if not nota:
                continue
            try:
                float(str(nota))
            except (ValueError, TypeError):
                continue
            # Subir hasta encontrar nombre
            el = barra.parent
            nombre = ""
            for _ in range(5):
                if not el:
                    break
                for child in el.children:
                    if hasattr(child, 'select') and child.select(".progress"):
                        continue
                    txt = child.get_text(strip=True) if hasattr(child, 'get_text') else str(child).strip()
                    if txt and len(txt) > 2 and not re.match(r"^[0-9. ]+$", txt):
                        nombre = txt[:80]
                        break
                if nombre:
                    break
                el = el.parent
            if nombre:
                _agregar_nota(notas, nombre, str(nota), basal_notas)

    # Fallback tablas
    if not notas:
        for fila in soup.select("table tr")[1:]:
            celdas = fila.select("td")
            if len(celdas) >= 2:
                materia = celdas[0].get_text(strip=True)
                nota    = celdas[1].get_text(strip=True)
                if materia and nota and len(materia) > 1:
                    _agregar_nota(notas, materia, nota, basal_notas)

    logger.info(f"Calificaciones: {len(notas)} con nota (de {len(bloques)} bloques trimestre)")
    return notas

def _agregar_nota(notas: list, materia: str, nota: str, basal_notas: dict):
    """Helper para agregar nota a la lista evitando duplicados."""
    materia = materia.strip()[:80]
    nota    = nota.strip()
    if not materia or len(materia) < 2:
        return
    if any(n["materia"] == materia for n in notas):
        return
    try:
        nn  = float(nota.replace(",", "."))
        if nn > 100:  # no es una nota válida
            return
        est = "Aprobada" if nn >= 65 else "REPROBADA"
    except ValueError:
        nn, est = None, ""
    notas.append({
        "materia": materia, "nota": nota, "nota_num": nn,
        "nota_anterior": basal_notas.get(materia, "(sin historial)"),
        "cambio": nota != basal_notas.get(materia),
        "estado": est, "fecha": "",
    })


# ── ASISTENCIA ────────────────────────────────────────────────────────────────

def revisar_asistencia(driver: WootITClient, basal: dict) -> dict:
    result = {"porcentaje": None, "total_ausencias": 0, "riesgo": False, "detalle": []}

    # Intentar via REST backend.wootit.com/v1/
    rows_rest = driver.get_asistencia_rest()
    if rows_rest:
        logger.info(f"Asistencia REST: {len(rows_rest)} items")
        for row in (rows_rest if isinstance(rows_rest, list) else []):
            if isinstance(row, dict):
                m   = str(row.get("materia") or row.get("curso") or row.get("MATERIA") or "")
                aus = str(row.get("ausencias") or row.get("faltas") or row.get("AUSENCIAS") or "0")
                pct = str(row.get("porcentaje") or row.get("PCT") or "")
                if m:
                    result["detalle"].append({"materia": m, "ausencias": aus, "pct": pct})
                    try: result["total_ausencias"] += int(aus)
                    except ValueError: pass
        if result["detalle"]:
            return result

    # Intentar via CFC JSON
    r = driver.get_asistencia_json()
    rows = WootITClient.query_to_dicts(r)
    if rows:
        logger.info(f"Asistencia JSON: {len(rows)} filas | cols={list(rows[0].keys()) if rows else []}")
        for row in rows:
            m   = row.get("MATERIA") or row.get("CURSONOMBRE") or ""
            aus = str(row.get("AUSENCIAS") or row.get("FALTAS") or "0")
            pct = str(row.get("PORCENTAJE") or row.get("PCT") or "")
            if m:
                result["detalle"].append({"materia": m, "ausencias": aus, "pct": pct})
                try: result["total_ausencias"] += int(aus)
                except ValueError: pass
        logger.info(f"Asistencia: {result['total_ausencias']} ausencias totales")
        return result

    # Fallback HTML
    soup = driver.get_asistencia_html()
    for sel in [".porcentaje-asistencia", ".pct-asistencia", "strong", "b"]:
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
    for fila in soup.select("table tr")[1:]:
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


# ── BOLETA / ANOTACIONES ──────────────────────────────────────────────────────

def revisar_seccion_simple(driver: WootITClient, seccion_key: str,
                           basal: dict, pregunta_claude: str) -> list:
    if seccion_key == "boleta":
        soup = driver.get_boleta_html()
    elif seccion_key == "anotaciones":
        soup = driver.get_anotaciones_html()
    else:
        return []

    items = []
    for fila in soup.select("table tr, .fila, .row-item, li")[1:]:
        txt = fila.get_text(separator=" | ", strip=True)
        if txt and len(txt) > 3:
            items.append({"detalle": txt})
    return items


# ── AULA VIRTUAL ──────────────────────────────────────────────────────────────

def revisar_aula_virtual(driver: WootITClient, ventana_desde, basal: dict) -> dict:
    tareas = []

    for filtro in ["porentregar", "todos"]:
        raw = driver.get_posts_aula_virtual(filtro=filtro)

        # La respuesta puede tener MAIN, QSHOW u otras keys
        for key in ["MAIN", "QSHOW", "DATA", ""]:
            posts = (WootITClient.query_to_dicts(raw.get(key, {}))
                     if key else WootITClient.query_to_dicts(raw))
            if posts:
                logger.info(f"AV posts ({filtro}/{key}): {len(posts)} | "
                            f"cols={list(posts[0].keys()) if posts else []}")
                break

        for post in posts[:15]:
            nombre  = (post.get("TITULO") or post.get("NOMBRE") or "Sin nombre")
            materia = (post.get("CURSONOMBRE") or post.get("MATERIA") or "")
            fecha   = (post.get("FECHA_ENTREGA") or post.get("FECHAENTREGA") or
                       post.get("FECHA") or "")
            id_post = post.get("ID") or post.get("IDPOST")
            dias    = _dias_hasta(fecha)

            instrucciones = ""
            if id_post:
                try:
                    det = driver.get_post_detalle(int(id_post))
                    instrucciones = str(
                        det.get("DESCRIPCION") or det.get("CUERPO") or "")[:600]
                except Exception:
                    pass

            tareas.append({
                "nombre": nombre, "materia": materia,
                "fecha_limite": _fecha_legible(fecha),
                "dias_restantes": dias,
                "estado": "atrasada" if dias < 0 else "pendiente",
                "instrucciones": instrucciones, "materiales": [],
            })

        if tareas:
            break

    atrasadas = len([t for t in tareas if t.get("estado") == "atrasada"])
    logger.info(f"Aula virtual: {len(tareas)} tareas, {atrasadas} atrasadas")
    return {"tareas": tareas, "total_pendientes": len(tareas), "total_atrasadas": atrasadas}


# ── AGENDA ────────────────────────────────────────────────────────────────────

def revisar_agenda(driver: WootITClient, basal: dict) -> list:
    raw = driver.get_proximos_eventos()
    procesados = []

    for seccion_key in ["EVENTOSAV", "EVENTOS"]:
        eventos = WootITClient.query_to_dicts(raw.get(seccion_key, {}))
        for ev in eventos:
            titulo  = str(ev.get("TITULO") or ev.get("NOMBRE") or "")
            materia = str(ev.get("CURSONOMBRE") or ev.get("MATERIA") or "")
            fecha_v = ev.get("FECHA") or ev.get("FECHAENTREGA") or ev.get("START") or ""
            dias    = _dias_hasta(fecha_v)
            fecha_s = _fecha_legible(fecha_v)
            tl      = titulo.lower()

            if any(t in tl for t in ["examen", "parcial"]):   tipo = "examen"
            elif "quiz" in tl:                                  tipo = "quiz"
            elif "prueba" in tl:                                tipo = "prueba"
            elif any(t in tl for t in ["tarea", "entrega"]):   tipo = "tarea"
            elif any(t in tl for t in ["feriado", "asueto",
                                        "vacacion", "semana santa"]): tipo = "feriado"
            else:                                               tipo = "actividad"

            procesados.append({
                "titulo": titulo, "materia": materia, "tipo": tipo,
                "fecha": fecha_s, "dias_restantes": dias,
                "urgencia": _nivel_urgencia(tipo, dias), "temario": [],
            })

    procesados.sort(key=lambda x: (
        {"CRITICA": 0, "ALTA": 1, "MEDIA": 2, "BAJA": 3}.get(x["urgencia"], 4),
        x["dias_restantes"]
    ))
    logger.info(f"Agenda: {len(procesados)} eventos")
    return procesados if procesados else [{"info": "Sin eventos próximos"}]


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
