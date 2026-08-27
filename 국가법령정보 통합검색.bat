@echo off
setlocal
cd /d "%~dp0"
set "APP_PYTHON=%~dp0_build\.venv_build\Scripts\pythonw.exe"
if exist "%APP_PYTHON%" (
    start "" "%APP_PYTHON%" "%~dp0molit_cgm_expc_qt.py"
) else (
    start "" pythonw.exe "%~dp0molit_cgm_expc_qt.py"
)
endlocal
exit /b
