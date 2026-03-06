-- ════════════════════════════════════════════
-- ColegioCR — Schema Supabase
-- Ejecutar en: Supabase > SQL Editor
-- ════════════════════════════════════════════

-- Mensajes / Comunicados
CREATE TABLE IF NOT EXISTS mensajes (
    id              BIGSERIAL PRIMARY KEY,
    estudiante      TEXT NOT NULL,
    asunto          TEXT,
    remitente       TEXT,
    fecha_mensaje   TIMESTAMPTZ,
    cuerpo          TEXT,
    resumen         TEXT,
    categoria       TEXT,  -- circular, cobro, autorizacion, actividad, disciplinario, evento
    urgencia        TEXT,  -- alta, media, baja
    requiere_accion BOOLEAN DEFAULT FALSE,
    ya_leido        BOOLEAN DEFAULT FALSE,
    tiene_adjunto   BOOLEAN DEFAULT FALSE,
    adjunto_nombre  TEXT,
    adjunto_contenido TEXT,
    fecha_extraccion TIMESTAMPTZ DEFAULT NOW(),
    turno           TEXT
);

-- Calificaciones
CREATE TABLE IF NOT EXISTS calificaciones (
    id              BIGSERIAL PRIMARY KEY,
    estudiante      TEXT NOT NULL,
    materia         TEXT,
    nota            NUMERIC(5,2),
    nota_anterior   NUMERIC(5,2),
    variacion       NUMERIC(5,2),
    fecha_registro  TIMESTAMPTZ,
    fecha_extraccion TIMESTAMPTZ DEFAULT NOW()
);

-- Asistencia
CREATE TABLE IF NOT EXISTS asistencia (
    id              BIGSERIAL PRIMARY KEY,
    estudiante      TEXT NOT NULL,
    fecha           DATE,
    tipo            TEXT,  -- ausencia, tardia
    materia         TEXT,
    periodo         TEXT,
    fecha_extraccion TIMESTAMPTZ DEFAULT NOW()
);

-- Anotaciones
CREATE TABLE IF NOT EXISTS anotaciones (
    id              BIGSERIAL PRIMARY KEY,
    estudiante      TEXT NOT NULL,
    fecha           DATE,
    tipo            TEXT,  -- disciplinaria, academica
    descripcion     TEXT,
    profesor        TEXT,
    fecha_extraccion TIMESTAMPTZ DEFAULT NOW()
);

-- Tareas Aula Virtual
CREATE TABLE IF NOT EXISTS tareas (
    id              BIGSERIAL PRIMARY KEY,
    estudiante      TEXT NOT NULL,
    materia         TEXT,
    nombre          TEXT,
    fecha_limite    DATE,
    descripcion     TEXT,
    adjunto_resumen TEXT,
    estado          TEXT DEFAULT 'pendiente',
    fecha_extraccion TIMESTAMPTZ DEFAULT NOW()
);

-- Ejecuciones (log de cada corrida)
CREATE TABLE IF NOT EXISTS ejecuciones (
    id              BIGSERIAL PRIMARY KEY,
    turno           TEXT,
    estado          TEXT,  -- exitoso, error_login, error_parcial
    detalle         TEXT,
    correo_enviado  BOOLEAN DEFAULT FALSE,
    fecha_ejecucion TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_mensajes_estudiante ON mensajes(estudiante);
CREATE INDEX IF NOT EXISTS idx_mensajes_fecha ON mensajes(fecha_mensaje);
CREATE INDEX IF NOT EXISTS idx_calificaciones_estudiante ON calificaciones(estudiante);
CREATE INDEX IF NOT EXISTS idx_tareas_fecha_limite ON tareas(fecha_limite);
