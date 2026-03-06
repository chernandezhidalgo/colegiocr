@echo off
echo ============================================================
echo  INSTALACION — ColegioCR Revision Automatica
echo ============================================================
echo.
echo [1/3] Instalando dependencias Python...
pip install selenium webdriver-manager beautifulsoup4 lxml ^
    pdfplumber pytesseract Pillow requests anthropic

echo.
echo [2/3] Creando directorios necesarios...
mkdir C:\Scripts\ColegioCR\logs 2>nul
mkdir C:\Scripts\ColegioCR\basal 2>nul
mkdir C:\Scripts\ColegioCR\adjuntos_temp 2>nul
mkdir C:\Scripts\ColegioCR\modules 2>nul

echo.
echo [3/3] Listo. Recuerda:
echo   - Instalar Tesseract OCR desde:
echo     https://github.com/UB-Mannheim/tesseract/wiki
echo   - Configurar contraseñas en config.py
echo   - Crear las 3 tareas en Programador de Tareas Windows
echo.
pause
