"""
Script de diagnóstico: descarga los JS del portal y extrae endpoints CFC.
Se ejecuta en GitHub Actions donde hay acceso directo a wootit.com.
"""
import re
import os
import urllib.request

BASE = "https://www.wootit.com/adventistacademy"
COOKIES = os.environ.get("WOOTIT_COOKIES", "")

SCRIPTS = [
    # Comunicación (confirmados en imágenes)
    f"{BASE}/comunicacion/js/recibidos.js?v=28",
    f"{BASE}/comunicacion/js/mensaje.js?v=36",
    # Calificaciones (patrón deducido)
    f"{BASE}/calificaciones/js/calificaciones.js?v=1",
    f"{BASE}/calificaciones/js/calificaciones.js?v=2",
    f"{BASE}/calificaciones/js/calificaciones.js?v=3",
    f"{BASE}/calificaciones/js/calificaciones.js?v=4",
    f"{BASE}/calificaciones/js/calificaciones.js?v=5",
    f"{BASE}/calificaciones/js/calificaciones.js?v=6",
    f"{BASE}/calificaciones/js/calificaciones.js?v=7",
    f"{BASE}/calificaciones/js/calificaciones.js?v=8",
    f"{BASE}/calificaciones/js/calificaciones.js?v=9",
    f"{BASE}/calificaciones/js/calificaciones.js?v=10",
    f"{BASE}/calificaciones/js/calificaciones.js",
    f"{BASE}/calificaciones/js/estudiante.js",
    f"{BASE}/calificaciones/js/notas.js",
    # Asistencia
    f"{BASE}/asistenciayconductaEst/js/asistencia.js",
    f"{BASE}/asistenciayconductaEst/js/asisEst.js",
    f"{BASE}/asistenciayconductaEst/js/asistenciayconducta.js",
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Cookie": COOKIES,
    "Referer": f"{BASE}/home/",
}

print("=== DIAGNÓSTICO JS ENDPOINTS ===")
found_any = False
for url in SCRIPTS:
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as r:
            if r.status == 200:
                content = r.read().decode('utf-8', errors='ignore')
                cfcs = re.findall(r'[\w/.-]+\.cfc[?][^"\'<\s]{0,200}', content)
                methods = re.findall(r'method[=:]["\'"]?(\w+)', content)
                ajax_urls = re.findall(r'url\s*:\s*["\']([^"\']+\.cfc[^"\']*)["\']', content)
                if cfcs or ajax_urls:
                    print(f"\n✅ {url.split('/')[-1].split('?')[0]}")
                    for c in set(cfcs)[:8]:
                        print(f"   CFC: {c}")
                    for a in set(ajax_urls)[:8]:
                        print(f"   AJAX: {a}")
                    if methods:
                        print(f"   Methods: {sorted(set(methods))[:10]}")
                    found_any = True
                else:
                    print(f"   {url.split('/')[-1].split('?')[0]}: cargó ({len(content)} chars) sin CFCs")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"   {url.split('/')[-1].split('?')[0]}: HTTP {e.code}")
    except Exception as e:
        print(f"   {url.split('/')[-1].split('?')[0]}: {e}")

if not found_any:
    print("\n⚠️  Ningún JS con endpoints encontrado")
