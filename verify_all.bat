@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set PYTHONUTF8=1

if exist ".venv\Scripts\python.exe" (
    set "PY_CMD=.venv\Scripts\python.exe"
    set "PYTEST_CMD=.venv\Scripts\pytest.exe"
) else if exist "..\razropay_venv\Scripts\python.exe" (
    set "PY_CMD=..\razropay_venv\Scripts\python.exe"
    set "PYTEST_CMD=..\razropay_venv\Scripts\pytest.exe"
) else (
    set "PY_CMD=python"
    set "PYTEST_CMD=pytest"
)

echo ==============================================================================
echo MandateGuard Windows Verification Suite
echo ==============================================================================

echo [Stage 1/5] Running 60-Second Judge Proof...
%PY_CMD% scripts\demo60.py
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Demo failed!
    exit /b %ERRORLEVEL%
)

echo.
echo [Stage 2/5] Running Pytest Suite (299 tests)...
%PYTEST_CMD% -q
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Pytest suite failed!
    exit /b %ERRORLEVEL%
)

echo.
echo [Stage 3/5] Running Security Regressions ^& RecoveryTruth Contract...
%PY_CMD% scripts\security_regression_check.py
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
%PY_CMD% scripts\recoverytruth_check.py
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%

echo.
echo [Stage 4/5] Running Hardening Gate ^& Claims Verification...
%PY_CMD% scripts\hardening_check.py
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
%PY_CMD% scripts\claims_check.py
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%

echo.
echo [Stage 5/5] Checking Release Invariants ^& Evidence Ledger...
%PY_CMD% scripts\check_release.py
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%

echo.
echo ==============================================================================
echo ALL STAGES PASSED: MandateGuard is VERIFIED and Submission Ready!
echo ==============================================================================
pause
