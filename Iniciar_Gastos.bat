@echo off
title Control de Gastos - Local
cd /d "%~dp0"
echo ==================================================
echo Iniciando aplicacion de Control de Gastos...
echo La base de datos se guardara en tu disco local.
echo ==================================================

:: Activar el entorno virtual e iniciar la app
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
    start http://127.0.0.1:5000
    python app.py
) else (
    echo [ERROR] No se encontro la carpeta 'venv'. Asegurate de que el entorno virtual de Python esta creado.
    pause
)
