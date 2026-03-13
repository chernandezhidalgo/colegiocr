"""
Módulo de generación del reporte HTML para el correo.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

TZ_CR = ZoneInfo('America/Costa_Rica')


def _urgentes(datos_estudiantes: list) -> list:
    urgentes = []
    for est in datos_estudiantes:
        # Mensajes con urgencia Alta
        for msg in est.get('mensajes', []):
            if msg.get('urgencia') == 'Alta':
                urgentes.append({
                    'estudiante': est['nombre_corto'],
                    'tipo': 'MENSAJE URGENTE',
                    'asunto': msg.get('asunto', 'Ver análisis'),
                    'detalle': msg.get('razon_urgencia', ''),
                })
        
        # Agenda: Identificar pruebas/quizzes en los próximos 15 días
        for evento in est.get('agenda', []):
            if evento.get('tipo') == 'agenda_detallada':
                analisis = evento.get('analisis_visual', '').lower()
                if any(p in analisis for p in ['examen', 'prueba', 'quiz', 'evaluación']):
                    urgentes.append({
                        'estudiante': est['nombre_corto'],
                        'tipo': 'PRUEBA PRÓXIMA',
                        'asunto': 'Exámenes/Quizzes detectados en agenda',
                        'detalle': 'Ver sección de Agenda para temarios y fechas.',
                    })
    return urgentes


def _seccion_mensajes(mensajes: list) -> str:
    if not mensajes:
        # R1: Distinguir "sin datos" vs "error"
        return " ℹ️ Sin mensajes nuevos en esta ventana temporal (sección accedida correctamente).\n"
    lineas = []
    for m in mensajes:
        if 'error' in m:
            lineas.append(f" ⚠️ {m['error']}\n")
            continue
        if 'analisis_visual' in m:
            lineas.append(f" [ANÁLISIS VISUAL]\n{m['analisis_visual']}\n")
            continue
        adjunto_txt = 'Sin adjunto'
        for adj in m.get('adjuntos', []):
            adjunto_txt = f"Adjunto '{adj['nombre']}': {adj['contenido'][:300]}..."
        
        lineas.append(
            f" • Asunto: {m.get('asunto', '')}\n"
            f"   De: {m.get('remitente', '')} | Fecha: {m.get('fecha', '')}\n"
            f"   Estado: {m.get('estado', '')}\n"
            f"   Resumen: {m.get('cuerpo', '')[:400]}\n"
            f"   Adjunto: {adjunto_txt}\n"
            f"   Urgencia: {m.get('urgencia', '')} — {m.get('razon_urgencia', '')}\n"
        )
    return "\n".join(lineas)


def _lista_simple(items: list) -> str:
    if not items:
        # R1: Distinguir "sin datos" vs "error"
        return " ℹ️ Sin cambios detectados (sección accedida correctamente).\n"
    lineas = []
    for it in items:
        if 'error' in it:
            lineas.append(f" ⚠️ {it['error']}")
        elif 'analisis_visual' in it:
            lineas.append(f" {it['analisis_visual']}")
        else:
            lineas.append(f" • {it.get('detalle', str(it))}")
    return "\n".join(lineas) + "\n"


def _aula_virtual_txt(av: dict) -> str:
    if 'error' in av:
        return f" ⚠️ {av['error']}\n"
    lineas = [" Tareas por entregar:"]
    for t in av.get('tareas', []):
        if 'analisis_visual' in t:
            lineas.append(f" {t['analisis_visual']}")
        else:
            lineas.append(f" • {t.get('detalle', '')}")
    if av.get('analisis_completo'):
        lineas.append(f"\n Análisis completo:\n {av['analisis_completo']}")
    return "\n".join(lineas) + "\n"


def _seccion_calificaciones(califs: list) -> str:
    if not califs:
        # R1: Distinguir "sin datos" vs "error"
        return " ℹ️ Sin cambios detectados (sección accedida correctamente).\n"
    lineas = []
    for c in califs:
        if 'error' in c:
            lineas.append(f" ⚠️ {c['error']}")
        elif 'analisis_visual' in c:
            lineas.append(f" {c['analisis_visual']}")
        else:
            lineas.append(
                f" • {c.get('materia', '')} | Anterior: {c.get('nota_anterior', '')} "
                f"→ Nueva: {c.get('nota_nueva', '')} | Fecha: {c.get('fecha', '')}"
            )
    return "\n".join(lineas) + "\n"


def generar_reporte(label_turno: str, datos_estudiantes: list) -> str:
    ahora = datetime.now(TZ_CR)
    fecha_fmt = ahora.strftime('%d/%m/%Y')
    hora_fmt = ahora.strftime('%H:%M')
    sep = "━" * 50
    
    lineas = [
        sep,
        f"REVISIÓN {label_turno} — Alajuela Adventist Academy",
        f"Fecha: {fecha_fmt} | Hora de generación: {hora_fmt} CR",
        sep,
        "",
        "▶ 1. RESUMEN EJECUTIVO — ATENCIÓN URGENTE",
        "",
    ]
    
    urgentes = _urgentes(datos_estudiantes)
    if urgentes:
        for u in urgentes:
            lineas.append(f" 🔴 [{u['estudiante']}] {u['tipo']}: {u['asunto']} — {u['detalle']}")
    else:
        lineas.append(" Sin ítems urgentes en esta revisión.")
    
    for est in datos_estudiantes:
        n = est['nombre_corto']
        lineas += [
            "", sep,
            f"▶ {n.upper()} HERNÁNDEZ — {est['grado']}",
            "",
            f"📨 COMUNICACIONES ({len([m for m in est.get('mensajes',[]) if 'error' not in m])} mensaje(s))",
            _seccion_mensajes(est.get('mensajes', [])),
            "📊 CALIFICACIONES",
            _seccion_calificaciones(est.get('calificaciones', [])),
            "📅 ASISTENCIA",
            _lista_simple(est.get('asistencia', [])),
            "📋 BOLETA",
            _lista_simple(est.get('boleta', [])),
            "📝 ANOTACIONES",
            _lista_simple(est.get('anotaciones', [])),
            "💻 AULA VIRTUAL",
            _aula_virtual_txt(est.get('aula_virtual', {})),
            "🗓️ AGENDA Y TEMARIOS (próximos 15 días)",
            _lista_simple(est.get('agenda', [])),
        ]
    
    lineas += [
        "", sep,
        "▶ 4. PENDIENTES ACUMULADOS Y FECHAS CRÍTICAS",
        " (Ver secciones de Aula Virtual y Agenda de cada estudiante arriba)",
        "",
        # R3: Footer corregido con horarios unificados
        f"Próxima revisión automática: 5:00 AM / 1:00 PM / 6:00 PM (hora CR)",
        f"Período de vigencia: 05/03/2026 → 20/11/2026",
        sep,
    ]
    
    return "\n".join(lineas)
