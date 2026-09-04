@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

if exist ".venv\Scripts\streamlit.exe" (
    set "ST_CMD=.venv\Scripts\streamlit.exe"
) else if exist "..\razropay_venv\Scripts\streamlit.exe" (
    set "ST_CMD=..\razropay_venv\Scripts\streamlit.exe"
) else (
    set "ST_CMD=streamlit"
)

echo ==============================================================================
echo Launching MandateGuard Policy Lab Evidence Dashboard
echo Using: %ST_CMD%
echo ==============================================================================

%ST_CMD% run app.py
pause
