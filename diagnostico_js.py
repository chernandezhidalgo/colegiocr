"""
Diagnóstico: descarga JS del portal WootIT y extrae endpoints CFC.
Guarda resultados en /tmp/logs/diagnostico_js.log para incluir en artefacto.
"""
import re, os, urllib.request, json

BASE = "https://www.wootit.com/adventistacademy"
COOKIES = os.environ.get("WOOTIT_COOKIES", "")
os.makedirs("/tmp/logs", exist_ok=True)

SCRIPTS_A_PROBAR = [
    # Comunicación
    (f"{BASE}/comunicacion/js/recibidos.js?v=28", "mensajes"),
    # Calificaciones — probar versiones 1-15
    *[(f"{BASE}/calificaciones/js/calificaciones.js?v={v}", "calificaciones") for v in range(1,16)],
    (f"{BASE}/calificaciones/js/calificaciones.js", "calificaciones"),
    (f"{BASE}/calificaciones/js/notas.js", "calificaciones"),
    (f"{BASE}/calificaciones/js/estudiante.js", "calificaciones"),
    # Asistencia — probar versiones 1-15
    *[(f"{BASE}/asistenciayconductaEst/js/asistencia.js?v={v}", "asistencia") for v in range(1,16)],
    (f"{BASE}/asistenciayconductaEst/js/asistencia.js", "asistencia"),
    (f"{BASE}/asistenciayconductaEst/js/asisEst.js", "asistencia"),
    *[(f"{BASE}/asistenciayconductaEst/js/asisEst.js?v={v}", "asistencia") for v in range(1,16)],
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Cookie": COOKIES,
    "Referer": f"{BASE}/home/",
    "Accept": "*/*",
}

resultados = {}
log_lines = ["=== DIAGNÓSTICO ENDPOINTS JS WOOTIT ===\n"]

for url, seccion in SCRIPTS_A_PROBAR:
    nombre = url.split('/')[-1].split('?')[0]
    clave = f"{seccion}/{nombre}"
    if clave in resultados:
        continue  # Ya encontrado para esta sección
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as r:
            if r.status == 200:
                content = r.read().decode('utf-8', errors='ignore')
                # Buscar URLs CFC en llamadas $.ajax, fetch, axios, $.get, $.post
                cfcs = re.findall(r'[\w/.-]+\.cfc[?][^"\'<>\s\\]{0,200}', content)
                ajax = re.findall(r'url\s*[:=]\s*["\']([^"\']+\.cfc[^"\']*)["\']', content)
                methods_used = re.findall(r'method\s*[:=]\s*["\'](\w+)["\']', content)
                all_endpoints = list(set(cfcs + ajax))
                
                if all_endpoints:
                    msg = f"\n✅ {url}\n"
                    for ep in all_endpoints[:10]:
                        msg += f"   ENDPOINT: {ep}\n"
                    if methods_used:
                        msg += f"   METHODS: {sorted(set(methods_used))[:10]}\n"
                    log_lines.append(msg)
                    print(msg)
                    resultados[clave] = all_endpoints
                else:
                    msg = f"   {nombre}: OK ({len(content)} chars) — sin endpoints CFC\n"
                    # Mostrar primeros 500 chars para inspección manual
                    preview = content[:500].replace('\n',' ')
                    msg += f"   PREVIEW: {preview}\n"
                    log_lines.append(msg)
                    print(msg)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            log_lines.append(f"   {nombre}: HTTP {e.code}\n")
            print(f"   {nombre}: HTTP {e.code}")
    except Exception as e:
        pass  # 404s silenciosos

log_lines.append(f"\n=== RESUMEN: {len(resultados)} archivos con endpoints ===\n")
log_lines.append(json.dumps(resultados, indent=2, ensure_ascii=False))

with open("/tmp/logs/diagnostico_js.log", "w") as f:
    f.writelines(log_lines)

print("\n=== FIN DIAGNÓSTICO ===")
print(f"Resultados guardados en /tmp/logs/diagnostico_js.log")
