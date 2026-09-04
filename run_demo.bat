@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

if exist ".venv\Scripts\python.exe" (
    set "PY_CMD=.venv\Scripts\python.exe"
) else if exist "..\razropay_venv\Scripts\python.exe" (
    set "PY_CMD=..\razropay_venv\Scripts\python.exe"
) else (
    set "PY_CMD=python"
)

echo ==============================================================================
echo Running MandateGuard Sixty-Second Judge Proof (Offline Deterministic)
echo Using: %PY_CMD%
echo ==============================================================================

%PY_CMD% scripts\demo60.py
pause
