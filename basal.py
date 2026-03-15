#!/usr/bin/env python3
"""
basal.py — Levantamiento basal completo de ColegioCR.

Propósito: captura el estado ACTUAL de TODOS los módulos y submódulos
del portal WootIT con una ventana temporal de 28 días hacia atrás.
Genera un informe HTML exhaustivo y lo envía por correo como
"Punto de Partida" del sistema de monitoreo.

Diferencias con revision_matutina.py:
  - Ventana temporal: últimas 4 semanas (28 días), no solo hoy
  - Calificaciones: historial completo disponible (todos los períodos)
  - Mensajes: todos los recibidos en 28 días (leídos y no leídos)
  - Agenda: próximos 60 días (no solo 15)
  - Aula Virtual: tareas entregadas Y pendientes
  - Asistencia: resumen del trimestre completo
  - Guarda el estado como basal.json para comparación futura
  - Subject especial: "[BASAL] ColegioCR — Punto de Partida"
"""
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from modules.browser import get_driver, login, cambiar_estudiante
from modules.clasificador import clasificar_mensaje
from modules.database import registrar_ejecucion, guardar_mensaje, guardar_calificacion
from modules.mailer import enviar_correo, enviar_alerta_error
from modules.wootit import (
    revisar_mensajes, revisar_calificaciones, revisar_asistencia,
    revisar_seccion_simple, revisar_aula_virtual, revisar_agenda,
    guardar_basal,
)

TZ_CR = ZoneInfo('America/Costa_Rica')

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs(config.DIR_LOGS, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(
            Path(config.DIR_LOGS) / f"basal_{date.today()}.log",
            encoding='utf-8'
        ),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# GENERACIÓN DEL INFORME BASAL HTML
# ═══════════════════════════════════════════════════════════════════════════════

def _css_basal():
    return """<style>
body{font-family:Arial,sans-serif;background:#F5F5F5;margin:0;padding:16px}
.cont{max-width:720px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.12)}
.hdr{background:#1A237E;color:white;padding:22px 26px}
.hdr h1{margin:0;font-size:22px}.hdr p{margin:4px 0 0;font-size:13px;opacity:.85}
.badge-basal{display:inline-block;background:#FFF9C4;color:#F57F17;border:1px solid #F9A825;padding:4px 14px;border-radius:12px;font-size:12px;font-weight:bold;margin-top:8px}
.bloque{padding:16px 22px;border-bottom:1px solid #EEE}
.bloque-titulo{font-weight:bold;font-size:13px;color:#555;text-transform:uppercase;letter-spacing:.5px;margin:0 0 10px}
.est-hdr{background:#E8EAF6;padding:14px 22px;border-top:3px solid #1A237E;font-weight:bold;font-size:15px;color:#1A237E}
.card{border-radius:6px;padding:11px 14px;margin:6px 0;font-size:13px}
.card-r{background:#FFEBEE;border-left:4px solid #D32F2F}
.card-o{background:#FBE9E7;border-left:4px solid #E64A19}
.card-y{background:#FFFDE7;border-left:4px solid #F9A825}
.card-g{background:#E8F5E9;border-left:4px solid #388E3C}
.card-b{background:#E3F2FD;border-left:4px solid #1565C0}
.card-gr{background:#FAFAFA;border-left:4px solid #9E9E9E}
table.t{width:100%;border-collapse:collapse;font-size:13px}
table.t th{background:#E8EAF6;padding:7px 10px;text-align:left;font-size:12px;color:#1A237E}
table.t td{padding:7px 10px;border-bottom:1px solid #EEE}
.rep{font-size:13px;color:#D32F2F;font-weight:bold}
.ok{font-size:13px;color:#388E3C}
.muted{color:#999;font-style:italic;font-size:12px}
.badge{display:inline-block;border-radius:10px;padding:2px 9px;font-size:11px;font-weight:bold;color:white}
ul.temario{margin:6px 0 0 16px;padding:0}
ul.temario li{margin:3px 0;font-size:12px;color:#333}
.footer{background:#F5F5F5;padding:14px 22px;font-size:11px;color:#999;text-align:center}
.sep{height:1px;background:#E0E0E0;margin:8px 0}
</style>"""


def _seccion_mensajes_basal(mensajes):
    if not mensajes:
        return '<p class="muted">Sin mensajes en las últimas 4 semanas.</p>'
    html = f'<p style="font-size:12px;color:#555;margin:0 0 8px">Total: {len(mensajes)} mensaje(s)</p>'
    for m in mensajes:
        if not isinstance(m, dict):
            continue
        if 'error' in m:
            html += f'<p class="muted">⚠ {m["error"]}</p>'; continue
        if 'analisis_visual' in m:
            html += f'<pre style="font-size:12px;white-space:pre-wrap">{m["analisis_visual"][:600]}</pre>'; continue
        urg = m.get('urgencia','Baja')
        cls = 'card-r' if urg=='Alta' else 'card-y' if urg=='Media' else 'card-gr'
        cat = m.get('categoria','')
        cat_txt = f' · {cat}' if cat else ''
        req = ' <span class="badge" style="background:#D32F2F">ACCIÓN</span>' if m.get('requiere_accion') else ''
        cuerpo = m.get('cuerpo','')[:300]
        html += f'''<div class="card {cls}" style="margin:6px 0">
          <strong>{m.get("asunto","Sin asunto")}</strong>{req}<br>
          <span style="font-size:12px;color:#666">✉ {m.get("remitente","")} · {m.get("fecha","")} · {m.get("estado","")}{cat_txt}</span>
          {"<div style='margin-top:5px;font-size:12px;color:#444;border-top:1px solid rgba(0,0,0,.08);padding-top:4px'>"+cuerpo+"</div>" if cuerpo else ""}
        </div>'''
    return html


def _seccion_calificaciones_basal(califs):
    if not califs:
        return '<p class="muted">Sin datos de calificaciones.</p>'
    if len(califs)==1 and 'analisis_visual' in califs[0]:
        return f'<pre style="font-size:12px;white-space:pre-wrap">{califs[0]["analisis_visual"]}</pre>'
    if len(califs)==1 and 'error' in califs[0]:
        return f'<p class="muted">⚠ {califs[0]["error"]}</p>'

    reprobadas = [c for c in califs if isinstance(c,dict) and 'REPROBADA' in c.get('estado','')]
    html = ''
    if reprobadas:
        html += f'<div class="card card-r" style="margin-bottom:10px">⚠ <strong>{len(reprobadas)} materia(s) reprobada(s)</strong></div>'

    html += '<table class="t"><tr><th>Materia</th><th>Nota</th><th>Estado</th></tr>'
    for c in califs:
        if not isinstance(c,dict) or 'analisis_visual' in c or 'error' in c:
            continue
        est  = c.get('estado','')
        cls  = 'rep' if 'REPROBADA' in est else 'ok' if est else ''
        html += f'<tr><td>{c.get("materia","")}</td><td class="{cls}"><strong>{c.get("nota","")}</strong></td><td class="{cls}">{est}</td></tr>'
    html += '</table>'
    return html


def _seccion_asistencia_basal(asistencia):
    if not isinstance(asistencia, dict):
        return '<p class="muted">Sin datos de asistencia.</p>'
    if 'error' in asistencia:
        return f'<p class="muted">⚠ {asistencia["error"]}</p>'
    if 'analisis_visual' in asistencia:
        return f'<pre style="font-size:12px;white-space:pre-wrap">{asistencia["analisis_visual"][:600]}</pre>'

    pct    = asistencia.get('porcentaje','N/D')
    aus    = asistencia.get('total_ausencias', 0)
    riesgo = asistencia.get('riesgo', False)
    det    = asistencia.get('detalle', [])

    alerta = '<div class="card card-r" style="margin-bottom:8px">⚠ <strong>RIESGO: asistencia bajo 85%</strong></div>' if riesgo else ''
    resumen = f'<p style="font-size:13px;margin:0 0 8px"><strong>Asistencia acumulada:</strong> {pct} &nbsp;|&nbsp; <strong>Ausencias totales:</strong> {aus}</p>'

    tabla = ''
    if det:
        tabla = '<table class="t"><tr><th>Materia</th><th>Ausencias</th><th>% Asistencia</th></tr>'
        for d in det:
            tabla += f'<tr><td>{d.get("materia","")}</td><td>{d.get("ausencias","")}</td><td>{d.get("pct","")}</td></tr>'
        tabla += '</table>'

    return alerta + resumen + tabla


def _seccion_agenda_basal(agenda):
    if not agenda:
        return '<p class="muted">Sin eventos en los próximos 60 días.</p>'
    html = ''
    for ev in agenda:
        if not isinstance(ev, dict):
            continue
        if 'analisis_visual' in ev:
            html += f'<pre style="font-size:12px;white-space:pre-wrap">{ev["analisis_visual"][:800]}</pre>'
            continue
        if 'error' in ev:
            html += f'<p class="muted">⚠ {ev["error"]}</p>'; continue

        urg  = ev.get('urgencia','BAJA')
        dias = ev.get('dias_restantes', 999)
        cls  = 'card-r' if urg=='CRITICA' else 'card-o' if urg=='ALTA' else 'card-y' if urg=='MEDIA' else 'card-g'
        icon = {'examen':'📝','quiz':'✏️','prueba':'📋','tarea':'📁','feriado':'🏖','actividad':'🎒'}.get(ev.get('tipo',''),'📌')

        cuando = 'HOY' if dias<=0 else 'MAÑANA' if dias==1 else f'en {dias} días'
        temario = ev.get('temario',[])
        tem_html = ''
        if temario:
            items = ''.join(f'<li>{t}</li>' for t in temario)
            tem_html = f'<div style="margin-top:7px"><strong style="font-size:12px">📖 Temario:</strong><ul class="temario">{items}</ul></div>'

        html += f'''<div class="card {cls}">
          <div style="display:flex;justify-content:space-between;align-items:flex-start">
            <span>{icon} <strong>{ev.get("titulo","")}</strong></span>
            <span style="font-size:12px;font-weight:bold">{cuando}</span>
          </div>
          <div style="font-size:12px;color:#555;margin-top:3px">📚 {ev.get("materia","")} · 📅 {ev.get("fecha","")} · {ev.get("tipo","")}</div>
          {tem_html}
        </div>'''
    return html or '<p class="muted">Sin evaluaciones próximas detectadas.</p>'


def _seccion_aula_basal(av):
    if not isinstance(av, dict):
        return '<p class="muted">Sin datos del Aula Virtual.</p>'
    if 'error' in av:
        return f'<p class="muted">⚠ {av["error"]}</p>'
    tareas = av.get('tareas',[])
    if not tareas:
        return '<p class="muted">Sin tareas registradas.</p>'
    if len(tareas)==1 and 'analisis_visual' in tareas[0]:
        return f'<pre style="font-size:12px;white-space:pre-wrap">{tareas[0]["analisis_visual"][:600]}</pre>'

    html = f'<p style="font-size:12px;color:#555;margin:0 0 8px">Total tareas: {len(tareas)} · Atrasadas: {av.get("total_atrasadas",0)}</p>'
    for t in sorted(tareas, key=lambda x: x.get('dias_restantes',999) if isinstance(x,dict) else 999):
        if not isinstance(t,dict):
            continue
        dias  = t.get('dias_restantes',999)
        est   = t.get('estado','pendiente')
        cls   = 'card-r' if est=='atrasada' else 'card-y' if dias<=3 else 'card-b'
        ins   = t.get('instrucciones','')[:300]
        ins_h = f'<div style="margin-top:5px;font-size:12px;color:#555;border-top:1px solid rgba(0,0,0,.08);padding-top:4px">{ins}</div>' if ins else ''
        mats  = t.get('materiales',[])
        mat_h = ''.join(f'<a href="{m["url"]}" style="font-size:11px;margin-right:8px;color:#1565C0">📎 {m["nombre"]}</a>' for m in mats)
        html += f'''<div class="card {cls}">
          <strong>{t.get("nombre","?")}</strong>
          <span class="badge" style="background:{"#D32F2F" if est=="atrasada" else "#388E3C"}">{est.upper()}</span><br>
          <span style="font-size:12px;color:#666">📚 {t.get("materia","")} · 📅 {t.get("fecha_limite","")}</span>
          {ins_h}
          {f"<div style='margin-top:4px'>{mat_h}</div>" if mat_h else ""}
        </div>'''
    return html


def _lista_simple_basal(items, vacio='Sin registros.'):
    if not items:
        return f'<p class="muted">{vacio}</p>'
    html = ''
    for it in items:
        if not isinstance(it,dict):
            continue
        if 'error' in it:
            html += f'<p class="muted">⚠ {it["error"]}</p>'
        elif 'analisis_visual' in it:
            html += f'<pre style="font-size:12px;white-space:pre-wrap">{it["analisis_visual"][:400]}</pre>'
        else:
            html += f'<div class="card card-b" style="margin:4px 0;font-size:13px">• {it.get("detalle",str(it))}</div>'
    return html or f'<p class="muted">{vacio}</p>'


def generar_html_basal(datos_estudiantes, fecha_desde, fecha_hasta):
    """Genera el HTML completo del informe basal."""
    ahora    = datetime.now(TZ_CR)
    fecha_fmt = ahora.strftime('%d/%m/%Y')
    hora_fmt  = ahora.strftime('%H:%M')

    # Resumen global
    total_reprobadas = sum(
        len([c for c in est.get('calificaciones',[]) if isinstance(c,dict) and 'REPROBADA' in c.get('estado','')])
        for est in datos_estudiantes
    )
    total_evals = sum(
        len([e for e in est.get('agenda',[]) if isinstance(e,dict) and 'error' not in e and 'analisis_visual' not in e])
        for est in datos_estudiantes
    )
    total_atrasadas = sum(
        est.get('aula_virtual',{}).get('total_atrasadas',0) if isinstance(est.get('aula_virtual'),dict) else 0
        for est in datos_estudiantes
    )
    riesgo_asist = any(
        est.get('asistencia',{}).get('riesgo',False) if isinstance(est.get('asistencia'),dict) else False
        for est in datos_estudiantes
    )

    # Header
    html = f'''<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<title>ColegioCR — Basal {fecha_fmt}</title>{_css_basal()}</head><body>
<div class="cont">
<div class="hdr">
  <h1>🏫 ColegioCR — Informe Basal</h1>
  <p>Alajuela Adventist Academy · {fecha_fmt} · Generado: {hora_fmt} CR</p>
  <span class="badge-basal">PUNTO DE PARTIDA · {fecha_desde} → {fecha_hasta}</span>
</div>'''

    # Resumen ejecutivo basal
    html += '<div class="bloque"><p class="bloque-titulo">📋 Estado General — Resumen Basal</p>'
    html += '<table class="t"><tr><th>Indicador</th><th>Estado</th></tr>'
    html += f'<tr><td>Materias reprobadas</td><td class="{"rep" if total_reprobadas else "ok"}">{"⚠ "+str(total_reprobadas)+" materia(s)" if total_reprobadas else "✅ Ninguna"}</td></tr>'
    html += f'<tr><td>Evaluaciones próximas (60 días)</td><td>{total_evals} detectada(s)</td></tr>'
    html += f'<tr><td>Tareas atrasadas</td><td class="{"rep" if total_atrasadas else "ok"}">{"⚠ "+str(total_atrasadas) if total_atrasadas else "✅ Ninguna"}</td></tr>'
    html += f'<tr><td>Riesgo de asistencia</td><td class="{"rep" if riesgo_asist else "ok"}">{"⚠ Sí — bajo 85%" if riesgo_asist else "✅ No"}</td></tr>'
    html += '</table></div>'

    # Sección por estudiante
    for est in datos_estudiantes:
        nombre = est.get('nombre_corto','?')
        grado  = est.get('grado','')
        html  += f'<div class="est-hdr">👤 {nombre.upper()} HERNÁNDEZ — {grado}</div>'

        # Agenda primero (lo más importante)
        html += '<div class="bloque"><p class="bloque-titulo">🗓 Agenda — Evaluaciones (próximos 60 días)</p>'
        html += _seccion_agenda_basal(est.get('agenda',[]))
        html += '</div>'

        # Aula Virtual — Tareas
        html += '<div class="bloque"><p class="bloque-titulo">💻 Aula Virtual — Tareas</p>'
        html += _seccion_aula_basal(est.get('aula_virtual',{}))
        html += '</div>'

        # Calificaciones
        html += '<div class="bloque"><p class="bloque-titulo">📊 Calificaciones (estado actual)</p>'
        html += _seccion_calificaciones_basal(est.get('calificaciones',[]))
        html += '</div>'

        # Asistencia
        html += '<div class="bloque"><p class="bloque-titulo">🏫 Asistencia (trimestre)</p>'
        html += _seccion_asistencia_basal(est.get('asistencia',{}))
        html += '</div>'

        # Mensajes (últimas 4 semanas)
        msgs = est.get('mensajes',[])
        html += f'<div class="bloque"><p class="bloque-titulo">📨 Comunicaciones — últimas 4 semanas ({len([m for m in msgs if isinstance(m,dict) and "error" not in m and "analisis_visual" not in m])} mensajes)</p>'
        html += _seccion_mensajes_basal(msgs)
        html += '</div>'

        # Anotaciones
        html += '<div class="bloque"><p class="bloque-titulo">📝 Anotaciones</p>'
        html += _lista_simple_basal(est.get('anotaciones',[]), 'Sin anotaciones registradas.')
        html += '</div>'

        # Boleta
        html += '<div class="bloque"><p class="bloque-titulo">📋 Boleta de Conducta</p>'
        html += _lista_simple_basal(est.get('boleta',[]), 'Sin registros en boleta.')
        html += '</div>'

    html += f'''<div class="footer">
    Basal generado el {fecha_fmt} a las {hora_fmt} CR · Período analizado: {fecha_desde} → {fecha_hasta}<br>
    Este informe sirve como punto de referencia para las revisiones diarias automáticas.<br>
    <a href="https://github.com/chernandezhidalgo/colegiocr" style="color:#999">github.com/chernandezhidalgo/colegiocr</a>
</div></div></body></html>'''
    return html


# ═══════════════════════════════════════════════════════════════════════════════
# ENRIQUECIMIENTO DE MENSAJES
# ═══════════════════════════════════════════════════════════════════════════════

def _enriquecer_mensajes(mensajes):
    for msg in mensajes:
        if 'error' in msg or 'analisis_visual' in msg:
            continue
        try:
            cl = clasificar_mensaje(msg.get('asunto',''), msg.get('cuerpo',''))
            msg.update({
                'categoria':       cl['categoria'],
                'requiere_accion': cl['requiere_accion'],
                'fecha_limite':    cl['fecha_limite'],
                'monto':           cl['monto'],
            })
            if cl['urgencia'] == 'alta':
                msg['urgencia'] = 'Alta'
            elif cl['urgencia'] == 'media' and msg.get('urgencia') == 'Baja':
                msg['urgencia'] = 'Media'
        except Exception as e:
            logger.warning(f'Error clasificando mensaje: {e}')
    return mensajes


# ═══════════════════════════════════════════════════════════════════════════════
# PERSISTENCIA EN SUPABASE
# ═══════════════════════════════════════════════════════════════════════════════

def _persistir_basal(datos_estudiantes):
    try:
        for est in datos_estudiantes:
            nombre = est.get('estudiante','')
            for msg in est.get('mensajes',[]):
                if isinstance(msg,dict) and 'error' not in msg and 'analisis_visual' not in msg:
                    guardar_mensaje(nombre, msg, 'basal')
            for cal in est.get('calificaciones',[]):
                if isinstance(cal,dict) and 'error' not in cal and 'analisis_visual' not in cal:
                    guardar_calificacion(nombre, cal)
        registrar_ejecucion('basal', 'exitoso', 'Levantamiento basal completado', True)
        logger.info("Datos basales persistidos en Supabase.")
    except Exception as e:
        logger.warning(f"No se pudo persistir en Supabase: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    logger.info("=" * 60)
    logger.info("ColegioCR — LEVANTAMIENTO BASAL COMPLETO")
    logger.info("=" * 60)

    # Ventana temporal: últimas 4 semanas
    ahora       = datetime.now(TZ_CR)
    fecha_hasta = ahora.strftime('%d/%m/%Y')
    fecha_desde_dt = ahora - timedelta(days=28)
    fecha_desde = fecha_desde_dt.strftime('%d/%m/%Y')
    ventana_desde = fecha_desde_dt.replace(hour=0, minute=0, second=0, microsecond=0)

    logger.info(f"Ventana temporal: {fecha_desde} → {fecha_hasta}")

    en_ci  = os.environ.get("CI","").lower() == "true"
    driver = get_driver(headless=en_ci)
    datos_estudiantes = []
    correo_ok         = False

    try:
        if not login(driver):
            logger.error("Login fallido.")
            enviar_alerta_error('BASAL', 'Login fallido en levantamiento basal.')
            sys.exit(1)

        # ── Estudiante 1: Carlos Emiliano ─────────────────────────────────
        logger.info("── Procesando Carlos Emiliano (basal completo) ──")
        basal_vacio = {}   # Sin basal previo — queremos TODO
        datos1 = {
            'estudiante':   config.HIJO1_LABEL,
            'nombre_corto': config.HIJO1_NOMBRE,
            'grado':        config.HIJO1_GRADO,
        }
        # Capturar screenshots diagnósticos de cada sección
        import os as _os
        _os.makedirs('/tmp/screenshots', exist_ok=True)

        datos1['mensajes']       = _enriquecer_mensajes(revisar_mensajes(driver, ventana_desde, basal_vacio))
        driver.save_screenshot('/tmp/screenshots/carlos_mensajes.png')

        datos1['calificaciones'] = revisar_calificaciones(driver, basal_vacio)
        driver.save_screenshot('/tmp/screenshots/carlos_calificaciones.png')

        datos1['asistencia']     = revisar_asistencia(driver, basal_vacio)
        driver.save_screenshot('/tmp/screenshots/carlos_asistencia.png')

        datos1['boleta']         = revisar_seccion_simple(driver, 'boleta',     basal_vacio, 'Lista todos los registros de conducta y boleta disponibles.')
        driver.save_screenshot('/tmp/screenshots/carlos_boleta.png')

        datos1['anotaciones']    = revisar_seccion_simple(driver, 'anotaciones', basal_vacio, 'Lista todas las anotaciones con fecha, tipo, descripcion y profesor.')
        datos1['aula_virtual']   = revisar_aula_virtual(driver, ventana_desde, basal_vacio)
        driver.save_screenshot('/tmp/screenshots/carlos_aula_virtual.png')

        datos1['agenda']         = revisar_agenda(driver, basal_vacio)
        driver.save_screenshot('/tmp/screenshots/carlos_agenda.png')
        datos_estudiantes.append(datos1)

        # Guardar basal de Carlos
        guardar_basal('emiliano', {
            'calificaciones': {c['materia']: c['nota'] for c in datos1['calificaciones']
                               if isinstance(c,dict) and 'materia' in c and 'nota' in c},
            'fecha_basal': ahora.isoformat(),
        })
        logger.info(f"Basal Carlos guardado: {len(datos1['calificaciones'])} materias, {len(datos1['mensajes'])} mensajes, {len(datos1['agenda'])} eventos agenda")

        # ── Estudiante 2: Starling Andrés ─────────────────────────────────
        logger.info("── Cambiando a Starling Andrés ──")
        cambio_ok = cambiar_estudiante(driver, 'Starling Andrés', '8° Grado')
        if not cambio_ok:
            logger.warning("Cambio a Starling falló — registrando error parcial")
            datos_estudiantes.append({
                'estudiante':   config.HIJO2_LABEL,
                'nombre_corto': config.HIJO2_NOMBRE,
                'grado':        config.HIJO2_GRADO,
                'mensajes':     [{'error': 'No procesado — error en cambio de perfil'}],
                'calificaciones': [], 'asistencia': {}, 'boleta': [],
                'anotaciones': [], 'aula_virtual': {}, 'agenda': [],
            })
        else:
            logger.info("── Procesando Starling Andrés (basal completo) ──")
            datos2 = {
                'estudiante':   config.HIJO2_LABEL,
                'nombre_corto': config.HIJO2_NOMBRE,
                'grado':        config.HIJO2_GRADO,
            }
            datos2['mensajes']       = _enriquecer_mensajes(revisar_mensajes(driver, ventana_desde, basal_vacio))
            driver.save_screenshot('/tmp/screenshots/starling_mensajes.png')
            datos2['calificaciones'] = revisar_calificaciones(driver, basal_vacio)
            driver.save_screenshot('/tmp/screenshots/starling_calificaciones.png')
            datos2['asistencia']     = revisar_asistencia(driver, basal_vacio)
            driver.save_screenshot('/tmp/screenshots/starling_asistencia.png')
            datos2['boleta']         = revisar_seccion_simple(driver, 'boleta',      basal_vacio, 'Lista todos los registros de conducta.')
            datos2['anotaciones']    = revisar_seccion_simple(driver, 'anotaciones',  basal_vacio, 'Lista todas las anotaciones.')
            datos2['aula_virtual']   = revisar_aula_virtual(driver, ventana_desde, basal_vacio)
            driver.save_screenshot('/tmp/screenshots/starling_aula_virtual.png')
            datos2['agenda']         = revisar_agenda(driver, basal_vacio)
            driver.save_screenshot('/tmp/screenshots/starling_agenda.png')
            datos_estudiantes.append(datos2)

            guardar_basal('andres', {
                'calificaciones': {c['materia']: c['nota'] for c in datos2['calificaciones']
                                   if isinstance(c,dict) and 'materia' in c and 'nota' in c},
                'fecha_basal': ahora.isoformat(),
            })
            logger.info(f"Basal Starling guardado: {len(datos2['calificaciones'])} materias, {len(datos2['mensajes'])} mensajes, {len(datos2['agenda'])} eventos agenda")

        # ── Generar y enviar informe ──────────────────────────────────────
        html_basal = generar_html_basal(datos_estudiantes, fecha_desde, fecha_hasta)
        asunto     = f"[BASAL] ColegioCR — Punto de Partida | {fecha_hasta}"
        correo_ok  = enviar_correo(asunto, html_basal)

        if correo_ok:
            logger.info(f"Informe basal enviado: {asunto}")
        else:
            logger.error("Fallo al enviar informe basal.")

    except Exception as e:
        logger.exception(f"Error inesperado en basal: {e}")
        try:
            registrar_ejecucion('basal', 'error_critico', str(e), False)
        except Exception:
            pass
        enviar_alerta_error('BASAL', str(e))
    finally:
        if datos_estudiantes:
            _persistir_basal(datos_estudiantes)
        driver.quit()
        logger.info("Levantamiento basal completado.")


if __name__ == '__main__':
    main()
