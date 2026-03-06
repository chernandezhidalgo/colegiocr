@echo off
REM ============================================================
REM  Crea las 3 tareas programadas en Programador de Tareas de Windows
REM  Ejecutar como ADMINISTRADOR
REM ============================================================

set SCRIPT=C:\Scripts\ColegioCR\revision_matutina.py
set PYTHON=python

echo Creando tarea MANANA (5:00 AM)...
schtasks /Create /TN "ColegioCR_Manana" /TR "%PYTHON% %SCRIPT% --turno manana" /SC DAILY /ST 05:00 /RU SYSTEM /F

echo Creando tarea MEDIODIA (1:00 PM)...
schtasks /Create /TN "ColegioCR_Mediodia" /TR "%PYTHON% %SCRIPT% --turno mediodia" /SC DAILY /ST 13:00 /RU SYSTEM /F

echo Creando tarea NOCHE (6:00 PM)...
schtasks /Create /TN "ColegioCR_Noche" /TR "%PYTHON% %SCRIPT% --turno noche" /SC DAILY /ST 18:00 /RU SYSTEM /F

echo.
echo ✅ Las 3 tareas fueron creadas exitosamente.
echo    Verifica en: Inicio > Programador de Tareas > Biblioteca
echo.
pause
