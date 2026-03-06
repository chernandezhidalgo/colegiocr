# ColegioCR — Revisión Automática Woot It

Sistema automatizado que monitorea el portal educativo Woot It de
Alajuela Adventist Academy y envía reportes por correo 3 veces al día.

## Estudiantes monitoreados
- Carlos Emiliano Hernández — 7° Grado
- Starling Andrés Hernández — 8° Grado

## Secciones revisadas
1. Comunicaciones (con clasificación automática)
2. Calificaciones
3. Asistencia
4. Boleta
5. Anotaciones
6. Aula Virtual
7. Agenda / Calendario

## Horario de ejecución (hora Costa Rica)
- 5:00 AM
- 1:00 PM
- 6:00 PM

## Configuración de Secrets en GitHub
Ir a Settings → Secrets and variables → Actions → New repository secret

| Secret | Descripción |
|--------|-------------|
| WOOTIT_USER | Usuario del portal Woot It |
| WOOTIT_PASS | Contraseña del portal Woot It |
| GMAIL_PASS | App Password de Gmail |
| SUPABASE_URL | URL del proyecto Supabase |
| SUPABASE_KEY | Service Role Key de Supabase |
| ANTHROPIC_API_KEY | API Key de Anthropic (opcional) |

## Base de datos
Ejecutar `supabase/schema.sql` en el SQL Editor de Supabase
para crear todas las tablas necesarias.
