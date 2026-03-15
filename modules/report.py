"""
report.py — Generación del reporte HTML para el correo diario.
Versión 3.0.0 — Mejoras M5, M9 implementadas:
  M5: Correo HTML con diseño visual, tarjetas por urgencia, semáforos de color
  M9: Subject diferenciado según urgencia del contenido
Ejecución única diaria a las 6:00 PM (hora CR).
"""
from datetime import datetime
from zoneinfo import ZoneInfo

TZ_CR = ZoneInfo('America/Costa_Rica')

# ── Paleta de colores ──────────────────────────────────────────────────────────
C = {
    'CRITICA':  '#D32F2F',
    'ALTA':     '#E64A19',
    'MEDIA':    '#F9A825',
    'BAJA':     '#388E3C',
    'INFO':     '#1565C0',
    'GRIS':     '#757575',
    'BG_CRITICA': '#FFEBEE',
    'BG_ALTA':    '#FBE9E7',
    'BG_MEDIA':   '#FFFDE7',
    'BG_BAJA':    '#E8F5E9',
    'BG_INFO':    '#E3F2FD',
    'AZUL':     '#1A237E',
    'AZUL_CLARO': '#E8EAF6',
}


# ══════════════════════════════════════════════════════════════════════════════
# BLOQUES HTML REUTILIZABLES
# ══════════════════════════════════════════════════════════════════════════════

def _css():
    return """
    <style>
      body { font-family: Arial, sans-serif; background: #F5F5F5; margin: 0; padding: 16px; }
      .contenedor { max-width: 680px; margin: 0 auto; background: white;
                    border-radius: 8px; overflow: hidden;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.12); }
      .header { background: #1A237E; color: white; padding: 20px 24px; }
      .header h1 { margin: 0; font-size: 20px; }
      .header p  { margin: 4px 0 0; font-size: 13px; opacity: 0.85; }
      .seccion-estudiante { border-top: 3px solid #1A237E; margin-top: 8px; }
      .titulo-estudiante { background: #E8EAF6; padding: 12px 20px;
                           font-weight: bold; font-size: 15px; color: #1A237E; }
      .bloque { padding: 14px 20px; border-bottom: 1px solid #EEEEEE; }
      .bloque-titulo { font-weight: bold; font-size: 13px; color: #555;
                       text-transform: uppercase; letter-spacing: 0.5px;
                       margin: 0 0 10px 0; }
      .tarjeta { border-radius: 6px; padding: 12px 14px; margin: 6px 0; }
      .tarjeta-critica { background: #FFEBEE; border-left: 4px solid #D32F2F; }
      .tarjeta-alta    { background: #FBE9E7; border-left: 4px solid #E64A19; }
      .tarjeta-media   { background: #FFFDE7; border-left: 4px solid #F9A825; }
      .tarjeta-baja    { background: #E8F5E9; border-left: 4px solid #388E3C; }
      .tarjeta-info    { background: #E3F2FD; border-left: 4px solid #1565C0; }
      .badge { display: inline-block; border-radius: 12px; padding: 2px 10px;
               font-size: 11px; font-weight: bold; color: white; }
      .cuenta-regresiva { font-size: 18px; font-weight: bold; float: right; }
      .temario-lista { margin: 8px 0 0 0; padding-left: 18px; }
      .temario-lista li { margin: 3px 0; font-size: 13px; color: #333; }
      .tabla-notas { width: 100%; border-collapse: collapse; font-size: 13px; }
      .tabla-notas th { background: #E8EAF6; padding: 6px 10px; text-align: left;
                        font-size: 12px; color: #1A237E; }
      .tabla-notas td { padding: 6px 10px; border-bottom: 1px solid #EEE; }
      .nota-reprobada { color: #D32F2F; font-weight: bold; }
      .nota-cambio { color: #E64A19; font-weight: bold; }
      .semaforo-ok  { color: #388E3C; font-weight: bold; }
      .semaforo-riesgo { color: #D32F2F; font-weight: bold; }
      .texto-muted  { color: #999; font-style: italic; font-size: 12px; }
      .footer { background: #F5F5F5; padding: 14px 20px;
                font-size: 11px; color: #999; text-align: center; }
      a { color: #1565C0; }
    </style>"""


def _badge(texto, color):
    return f'<span class="badge" style="background:{color}">{texto}</span>'


def _cuenta_regresiva_html(dias):
    if dias <= 0:
        return f'<span class="cuenta-regresiva" style="color:{C["CRITICA"]}">HOY</span>'
    if dias == 1:
        return f'<span class="cuenta-regresiva" style="color:{C["CRITICA"]}">MAÑANA</span>'
    if dias <= 5:
        return f'<span class="cuenta-regresiva" style="color:{C["ALTA"]}">En {dias} días</span>'
    if dias <= 10:
        return f'<span class="cuenta-regresiva" style="color:{C["MEDIA"]}">En {dias} días</span>'
    return f'<span class="cuenta-regresiva" style="color:{C["BAJA"]}">En {dias} días</span>'


def _clase_tarjeta(urgencia):
    mapa = {'CRITICA': 'critica', 'ALTA': 'alta', 'MEDIA': 'media', 'BAJA': 'baja'}
    return f"tarjeta tarjeta-{mapa.get(urgencia, 'info')}"


# ══════════════════════════════════════════════════════════════════════════════
# RESUMEN EJECUTIVO
# ══════════════════════════════════════════════════════════════════════════════

def _construir_alertas(datos_estudiantes):
    """Recopila todas las alertas críticas y altas de ambos estudiantes."""
    alertas = []
    for est in datos_estudiantes:
        nombre = est.get('nombre_corto', '')

        # Evaluaciones urgentes en agenda
        for ev in est.get('agenda', []):
            if not isinstance(ev, dict) or 'analisis_visual' in ev:
                continue
            dias = ev.get('dias_restantes', 999)
            urg  = ev.get('urgencia', 'BAJA')
            if urg in ('CRITICA', 'ALTA'):
                alertas.append({
                    'estudiante': nombre,
                    'nivel': urg,
                    'icono': '📝',
                    'texto': f"{ev.get('titulo', ev.get('tipo','Evaluación'))} — {ev.get('materia','')}",
                    'dias': dias,
                })

        # Tareas atrasadas en aula virtual
        av = est.get('aula_virtual', {})
        if isinstance(av, dict):
            for t in av.get('tareas', []):
                if isinstance(t, dict) and t.get('estado') == 'atrasada':
                    alertas.append({
                        'estudiante': nombre,
                        'nivel': 'CRITICA',
                        'icono': '📋',
                        'texto': f"Tarea ATRASADA: {t.get('nombre','?')} ({t.get('materia','')})",
                        'dias': t.get('dias_restantes', -1),
                    })

        # Notas reprobadas
        for cal in est.get('calificaciones', []):
            if isinstance(cal, dict) and cal.get('estado') == 'REPROBADA':
                alertas.append({
                    'estudiante': nombre,
                    'nivel': 'ALTA',
                    'icono': '📊',
                    'texto': f"REPROBADA: {cal.get('materia','?')} — {cal.get('nota','?')}",
                    'dias': 999,
                })

        # Mensajes urgentes
        for msg in est.get('mensajes', []):
            if isinstance(msg, dict) and msg.get('urgencia') == 'Alta':
                alertas.append({
                    'estudiante': nombre,
                    'nivel': 'ALTA',
                    'icono': '📨',
                    'texto': f"Mensaje urgente: {msg.get('asunto','?')}",
                    'dias': 999,
                })

        # Riesgo de asistencia
        asist = est.get('asistencia', {})
        if isinstance(asist, dict) and asist.get('riesgo'):
            alertas.append({
                'estudiante': nombre,
                'nivel': 'ALTA',
                'icono': '🏫',
                'texto': f"Riesgo asistencia: {asist.get('porcentaje','?')} — menos del 85%",
                'dias': 999,
            })

    alertas.sort(key=lambda x: {'CRITICA': 0, 'ALTA': 1}.get(x['nivel'], 2))
    return alertas


def _html_resumen_ejecutivo(datos_estudiantes):
    alertas = _construir_alertas(datos_estudiantes)
    if not alertas:
        return '''
        <div class="bloque">
          <p class="bloque-titulo">🔎 Resumen del día</p>
          <div class="tarjeta tarjeta-baja" style="text-align:center;padding:16px">
            <span style="font-size:22px">✅</span><br>
            <strong>Todo en orden</strong><br>
            <span class="texto-muted">Sin evaluaciones urgentes, tareas atrasadas ni notas reprobadas.</span>
          </div>
        </div>'''

    html = '<div class="bloque"><p class="bloque-titulo">🚨 Atención requerida</p>'
    for a in alertas:
        color_bg = C['BG_CRITICA'] if a['nivel'] == 'CRITICA' else C['BG_ALTA']
        color    = C[a['nivel']]
        badge    = _badge(a['nivel'], color)
        cuenta   = _cuenta_regresiva_html(a['dias']) if a['dias'] < 999 else ''
        html += f'''
        <div class="{_clase_tarjeta(a['nivel'])}" style="margin:6px 0">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>{a['icono']} <strong>[{a['estudiante']}]</strong> {a['texto']}</span>
            {cuenta}
          </div>
        </div>'''
    html += '</div>'
    return html


# ══════════════════════════════════════════════════════════════════════════════
# BLOQUES POR SECCIÓN
# ══════════════════════════════════════════════════════════════════════════════

def _html_agenda(agenda):
    if not agenda:
        return '<p class="texto-muted">Sin eventos en los próximos 15 días.</p>'
    if not isinstance(agenda, list):
        return '<p class="texto-muted">Sin eventos detectados.</p>'

    # Separar por semana
    esta_semana = [e for e in agenda if isinstance(e, dict) and 0 <= e.get('dias_restantes', 999) <= 7]
    proximos    = [e for e in agenda if isinstance(e, dict) and 8 <= e.get('dias_restantes', 999) <= 21]
    analisis    = [e for e in agenda if isinstance(e, dict) and 'analisis_visual' in e]
    errores     = [e for e in agenda if isinstance(e, dict) and 'error' in e]

    html = ''

    if analisis:
        for a in analisis:
            html += f'<div class="tarjeta tarjeta-info"><pre style="white-space:pre-wrap;font-size:12px">{a["analisis_visual"]}</pre></div>'

    for ev in esta_semana + proximos:
        urgencia  = ev.get('urgencia', 'BAJA')
        dias      = ev.get('dias_restantes', 999)
        tipo_icon = {'examen': '📝', 'quiz': '✏️', 'prueba': '📋',
                     'tarea': '📁', 'feriado': '🏖️', 'actividad': '🎒'
                     }.get(ev.get('tipo', ''), '📌')

        cuenta = _cuenta_regresiva_html(dias)
        badge  = _badge(ev.get('tipo', '').upper(), C.get(urgencia, C['GRIS']))

        temario_html = ''
        temario = ev.get('temario', [])
        if temario:
            items_html = ''.join(f'<li>{t}</li>' for t in temario)
            temario_html = f'''
            <div style="margin-top:8px">
              <strong style="font-size:12px;color:#555">📖 Temario de estudio:</strong>
              <ul class="temario-lista">{items_html}</ul>
            </div>'''

        html += f'''
        <div class="{_clase_tarjeta(urgencia)}" style="margin:8px 0">
          <div style="display:flex;justify-content:space-between;align-items:flex-start">
            <div>
              {tipo_icon} <strong>{ev.get('titulo','')}</strong> {badge}<br>
              <span style="font-size:12px;color:#555">
                📚 {ev.get('materia','')} &nbsp;|&nbsp; 📅 {ev.get('fecha','')}
              </span>
            </div>
            {cuenta}
          </div>
          {temario_html}
        </div>'''

    if errores:
        for e in errores:
            html += f'<div class="tarjeta tarjeta-info"><span class="texto-muted">⚠️ {e["error"]}</span></div>'

    if not html:
        html = '<p class="texto-muted">Sin evaluaciones próximas detectadas.</p>'
    return html


def _html_aula_virtual(av):
    if not isinstance(av, dict):
        return '<p class="texto-muted">Sin datos del Aula Virtual.</p>'
    if 'error' in av:
        return f'<p class="texto-muted">⚠️ {av["error"]}</p>'

    tareas = av.get('tareas', [])
    if not tareas:
        return '<p class="texto-muted">✅ Sin tareas pendientes.</p>'

    # Analisis visual como fallback
    if len(tareas) == 1 and isinstance(tareas[0], dict) and 'analisis_visual' in tareas[0]:
        return f'<pre style="white-space:pre-wrap;font-size:12px;background:#F9F9F9;padding:10px;border-radius:4px">{tareas[0]["analisis_visual"]}</pre>'

    html = ''
    atrasadas = av.get('total_atrasadas', 0)
    if atrasadas > 0:
        html += f'<div class="tarjeta tarjeta-critica" style="margin-bottom:10px">⚠️ <strong>{atrasadas} tarea(s) ATRASADA(S)</strong></div>'

    for t in sorted(tareas, key=lambda x: x.get('dias_restantes', 999) if isinstance(x, dict) else 999):
        if not isinstance(t, dict):
            continue
        dias   = t.get('dias_restantes', 999)
        estado = t.get('estado', 'pendiente')
        urg    = 'CRITICA' if estado == 'atrasada' else ('ALTA' if dias <= 2 else ('MEDIA' if dias <= 7 else 'BAJA'))
        cuenta = _cuenta_regresiva_html(dias) if dias != 999 else ''
        instruc = t.get('instrucciones', '')
        instruc_html = f'<div style="margin-top:6px;font-size:12px;color:#555;border-top:1px solid rgba(0,0,0,0.08);padding-top:6px">{instruc[:400]}</div>' if instruc else ''

        materiales = t.get('materiales', [])
        mat_html = ''
        if materiales:
            links = ' '.join(f'<a href="{m["url"]}" style="margin-right:8px">📎 {m["nombre"]}</a>'
                              for m in materiales)
            mat_html = f'<div style="margin-top:6px;font-size:12px">{links}</div>'

        html += f'''
        <div class="{_clase_tarjeta(urg)}" style="margin:6px 0">
          <div style="display:flex;justify-content:space-between;align-items:flex-start">
            <div>
              <strong>{t.get("nombre","?")}</strong><br>
              <span style="font-size:12px;color:#555">📚 {t.get("materia","")} &nbsp;|&nbsp; 📅 {t.get("fecha_limite","")}</span>
              {_badge("ATRASADA" if estado=="atrasada" else "PENDIENTE",
                      C["CRITICA"] if estado=="atrasada" else C["BAJA"])}
            </div>
            {cuenta}
          </div>
          {instruc_html}
          {mat_html}
        </div>'''
    return html


def _html_calificaciones(califs):
    if not califs:
        return '<p class="texto-muted">Sin datos de calificaciones.</p>'
    if len(califs) == 1 and isinstance(califs[0], dict) and 'analisis_visual' in califs[0]:
        return f'<pre style="white-space:pre-wrap;font-size:12px">{califs[0]["analisis_visual"]}</pre>'
    if len(califs) == 1 and isinstance(califs[0], dict) and 'error' in califs[0]:
        return f'<p class="texto-muted">⚠️ {califs[0]["error"]}</p>'

    filas = ''
    reprobadas = 0
    cambios = 0
    for c in califs:
        if not isinstance(c, dict):
            continue
        nota    = c.get('nota', '')
        estado  = c.get('estado', '')
        cambio  = c.get('cambio', False)
        es_rep  = 'REPROBADA' in estado
        if es_rep:
            reprobadas += 1
        if cambio:
            cambios += 1
        clase_nota = 'nota-reprobada' if es_rep else ('nota-cambio' if cambio else '')
        cambio_txt = f' ← era {c.get("nota_anterior","")}' if cambio else ''
        filas += f'''<tr>
          <td>{c.get("materia","")}</td>
          <td class="{clase_nota}">{nota}{cambio_txt}</td>
          <td>{"✅" if not es_rep and estado else "❌" if es_rep else ""} {estado}</td>
          <td style="font-size:11px;color:#999">{c.get("fecha","")}</td>
        </tr>'''

    resumen = ''
    if reprobadas:
        resumen += f'<div class="tarjeta tarjeta-critica" style="margin-bottom:8px">❌ <strong>{reprobadas} materia(s) reprobada(s)</strong></div>'
    if cambios:
        resumen += f'<div class="tarjeta tarjeta-media" style="margin-bottom:8px">🔄 <strong>{cambios} nota(s) actualizada(s)</strong></div>'

    return resumen + f'''
    <table class="tabla-notas">
      <tr><th>Materia</th><th>Nota</th><th>Estado</th><th>Fecha</th></tr>
      {filas}
    </table>'''


def _html_asistencia(asistencia):
    if not isinstance(asistencia, dict):
        return '<p class="texto-muted">Sin datos de asistencia.</p>'
    if 'error' in asistencia:
        return f'<p class="texto-muted">⚠️ {asistencia["error"]}</p>'
    if 'analisis_visual' in asistencia:
        return f'<pre style="white-space:pre-wrap;font-size:12px">{asistencia["analisis_visual"]}</pre>'

    pct        = asistencia.get('porcentaje', 'N/D')
    ausencias  = asistencia.get('total_ausencias', 0)
    riesgo     = asistencia.get('riesgo', False)
    detalle    = asistencia.get('detalle', [])

    clase_pct  = 'semaforo-riesgo' if riesgo else 'semaforo-ok'
    alerta_html = ''
    if riesgo:
        alerta_html = '<div class="tarjeta tarjeta-critica" style="margin-bottom:8px">⚠️ <strong>RIESGO: Asistencia por debajo del 85% requerido</strong></div>'

    filas = ''
    for d in detalle:
        filas += f'<tr><td>{d.get("materia","")}</td><td>{d.get("ausencias","")}</td><td>{d.get("pct","")}</td></tr>'

    tabla = f'''
    <table class="tabla-notas">
      <tr><th>Materia</th><th>Ausencias</th><th>% Asistencia</th></tr>
      {filas}
    </table>''' if filas else ''

    return f'''{alerta_html}
    <p>Asistencia general: <span class="{clase_pct}">{pct}</span> &nbsp;|&nbsp;
       Ausencias acumuladas: <strong>{ausencias}</strong></p>
    {tabla}'''


def _html_mensajes(mensajes):
    if not mensajes:
        return '<p class="texto-muted">Sin mensajes en el período.</p>'
    html = ''
    for m in mensajes:
        if not isinstance(m, dict):
            continue
        if 'error' in m:
            html += f'<p class="texto-muted">⚠️ {m["error"]}</p>'
            continue
        if 'analisis_visual' in m:
            html += f'<pre style="white-space:pre-wrap;font-size:12px">{m["analisis_visual"]}</pre>'
            continue
        urg  = m.get('urgencia', 'Baja')
        urg_key = urg.upper() if urg.upper() in C else 'BAJA'
        categoria = m.get('categoria', '')
        cat_txt = f' — {categoria}' if categoria else ''
        cuerpo = m.get('cuerpo', '')[:350]
        cuerpo_html = f'<div style="margin-top:6px;font-size:12px;color:#444;border-top:1px solid rgba(0,0,0,0.08);padding-top:6px">{cuerpo}</div>' if cuerpo else ''
        req_accion = m.get('requiere_accion', False)
        accion_badge = _badge('REQUIERE ACCIÓN', C['CRITICA']) if req_accion else ''
        html += f'''
        <div class="{_clase_tarjeta(urg_key)}" style="margin:6px 0">
          <strong>{m.get("asunto","Sin asunto")}</strong> {accion_badge}<br>
          <span style="font-size:12px;color:#666">
            ✉️ {m.get("remitente","")} &nbsp;|&nbsp; 📅 {m.get("fecha","")} &nbsp;|&nbsp;
            {m.get("estado","")} {cat_txt}
          </span>
          {cuerpo_html}
        </div>'''
    return html or '<p class="texto-muted">Sin mensajes nuevos.</p>'


def _html_lista_simple(items, msg_vacio='Sin registros.'):
    if not items:
        return f'<p class="texto-muted">{msg_vacio}</p>'
    html = ''
    for it in items:
        if not isinstance(it, dict):
            continue
        if 'error' in it:
            html += f'<p class="texto-muted">⚠️ {it["error"]}</p>'
        elif 'analisis_visual' in it:
            html += f'<pre style="white-space:pre-wrap;font-size:12px">{it["analisis_visual"]}</pre>'
        else:
            html += f'<div class="tarjeta tarjeta-info" style="margin:4px 0">• {it.get("detalle", str(it))}</div>'
    return html or f'<p class="texto-muted">{msg_vacio}</p>'


def _bloque(icono, titulo, contenido_html):
    return f'''
    <div class="bloque">
      <p class="bloque-titulo">{icono} {titulo}</p>
      {contenido_html}
    </div>'''


# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN POR ESTUDIANTE
# ══════════════════════════════════════════════════════════════════════════════

def _html_estudiante(est):
    nombre = est.get('nombre_corto', '?')
    grado  = est.get('grado', '')

    agenda = est.get('agenda', [])
    av     = est.get('aula_virtual', {})
    califs = est.get('calificaciones', [])

    # Semáforo rápido del estudiante
    tiene_critico = any(
        isinstance(e, dict) and e.get('urgencia') in ('CRITICA',)
        for e in agenda
    )
    tiene_reprobada = any(
        isinstance(c, dict) and 'REPROBADA' in c.get('estado', '')
        for c in califs
    )
    tiene_atrasada = (isinstance(av, dict) and av.get('total_atrasadas', 0) > 0)
    riesgo_asist   = isinstance(est.get('asistencia', {}), dict) and est.get('asistencia', {}).get('riesgo', False)

    if tiene_critico or tiene_atrasada:
        semaforo = f'<span style="color:{C["CRITICA"]};font-size:18px">🔴</span>'
    elif tiene_reprobada or riesgo_asist:
        semaforo = f'<span style="color:{C["ALTA"]};font-size:18px">🟠</span>'
    else:
        semaforo = f'<span style="color:{C["BAJA"]};font-size:18px">🟢</span>'

    return f'''
    <div class="seccion-estudiante">
      <div class="titulo-estudiante">
        {semaforo} &nbsp; {nombre.upper()} HERNÁNDEZ &nbsp;—&nbsp; {grado}
      </div>
      {_bloque("🗓️", "Agenda y Evaluaciones (próximos 15 días)", _html_agenda(agenda))}
      {_bloque("💻", "Aula Virtual — Tareas", _html_aula_virtual(av))}
      {_bloque("📊", "Calificaciones", _html_calificaciones(califs))}
      {_bloque("🏫", "Asistencia", _html_asistencia(est.get('asistencia', {})))}
      {_bloque("📨", "Comunicaciones", _html_mensajes(est.get('mensajes', [])))}
      {_bloque("📝", "Anotaciones", _html_lista_simple(est.get('anotaciones', []), 'Sin anotaciones registradas.'))}
      {_bloque("📋", "Boleta de Conducta", _html_lista_simple(est.get('boleta', []), 'Sin cambios en boleta.'))}
    </div>'''


# ══════════════════════════════════════════════════════════════════════════════
# SUBJECT DEL CORREO — M9
# ══════════════════════════════════════════════════════════════════════════════

def construir_asunto(datos_estudiantes):
    """
    M9: Subject diferenciado con urgencias detectadas.
    Ejemplos:
      🔴 ColegioCR | URGENTE: Carlos: Quiz Matemáticas (mañana) | 15/03/2026
      ✅ ColegioCR | Todo en orden | 15/03/2026
    """
    fecha = datetime.now(TZ_CR).strftime('%d/%m/%Y')
    criticos = []

    for est in datos_estudiantes:
        nombre = est.get('nombre_corto', '?')
        for ev in est.get('agenda', []):
            if not isinstance(ev, dict) or 'analisis_visual' in ev:
                continue
            dias = ev.get('dias_restantes', 999)
            urg  = ev.get('urgencia', 'BAJA')
            if urg == 'CRITICA':
                cuando = 'HOY' if dias <= 0 else ('mañana' if dias == 1 else f'en {dias} días')
                criticos.append(f"{nombre}: {ev.get('titulo', ev.get('tipo','Eval.'))} ({cuando})")

        av = est.get('aula_virtual', {})
        if isinstance(av, dict) and av.get('total_atrasadas', 0) > 0:
            n = av['total_atrasadas']
            criticos.append(f"{nombre}: {n} tarea(s) atrasada(s)")

    if criticos:
        resumen = ' | '.join(criticos[:3])
        return f"🔴 ColegioCR | URGENTE: {resumen} | {fecha}"

    # Verificar si hay notas reprobadas o alertas medias
    alertas_medias = []
    for est in datos_estudiantes:
        nombre = est.get('nombre_corto', '?')
        for cal in est.get('calificaciones', []):
            if isinstance(cal, dict) and 'REPROBADA' in cal.get('estado', ''):
                alertas_medias.append(f"{nombre}: {cal.get('materia','')} reprobada")
        for ev in est.get('agenda', []):
            if isinstance(ev, dict) and ev.get('urgencia') == 'ALTA' and 'analisis_visual' not in ev:
                alertas_medias.append(f"{nombre}: {ev.get('titulo','eval')} en {ev.get('dias_restantes','?')} días")

    if alertas_medias:
        resumen = ' | '.join(alertas_medias[:2])
        return f"🟡 ColegioCR | Atención: {resumen} | {fecha}"

    return f"✅ ColegioCR | Todo en orden | {fecha}"


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def generar_reporte(label_turno, datos_estudiantes):
    """Genera el HTML completo del correo diario."""
    ahora     = datetime.now(TZ_CR)
    fecha_fmt = ahora.strftime('%d/%m/%Y')
    hora_fmt  = ahora.strftime('%H:%M')

    secciones_est = ''.join(_html_estudiante(est) for est in datos_estudiantes)

    html = f'''<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ColegioCR — Reporte {fecha_fmt}</title>
  {_css()}
</head>
<body>
<div class="contenedor">

  <div class="header">
    <h1>🏫 ColegioCR — Reporte Diario</h1>
    <p>Alajuela Adventist Academy &nbsp;|&nbsp; {fecha_fmt} &nbsp;|&nbsp; Generado: {hora_fmt} CR</p>
  </div>

  {_html_resumen_ejecutivo(datos_estudiantes)}

  {secciones_est}

  <div class="footer">
    Próxima revisión automática: mañana a las 6:00 PM (hora CR) &nbsp;|&nbsp;
    Período de vigencia: 05/03/2026 → 20/11/2026<br>
    <a href="https://github.com/chernandezhidalgo/colegiocr">github.com/chernandezhidalgo/colegiocr</a>
  </div>

</div>
</body>
</html>'''
    return html
