@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Use an already installed interpreter. Never let py download a runtime.
set "PYTHON_MANAGER_AUTOMATIC_INSTALL=false"
set "PYLAUNCHER_ALLOW_INSTALL="
set "PYLAUNCHER_ALWAYS_INSTALL="
set "PYLAUNCHER_DRYRUN="
set "AQC_EXIT_CODE=2"
pushd "%~dp0" >nul 2>&1
if errorlevel 1 goto folder_error
if not exist "aqc_app\__main__.py" goto files_error

set "AQC_PY_SWITCH="
if defined AQC_PYTHON goto explicit_python
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -I -S -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "AQC_PY_EXE=%CD%\.venv\Scripts\python.exe"
        goto launch
    )
)
py -3 -I -S -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "AQC_PY_EXE=py"
    set "AQC_PY_SWITCH=-3"
    goto launch
)
python -I -S -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "AQC_PY_EXE=python"
    goto launch
)
echo AQC: Python 3.10 or newer was not found.
echo Install Python separately, or set AQC_PYTHON to an existing python.exe.
echo The saved-results app does not need RDKit, NumPy, Matplotlib, pip, or a virtual environment.
goto failed

:explicit_python
"%AQC_PYTHON%" -I -S -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo AQC: AQC_PYTHON must name an existing Python 3.10 or newer executable.
    echo Use an executable path without extra command-line arguments.
    goto failed
)
set "AQC_PY_EXE=%AQC_PYTHON%"

:launch
echo Starting AQC on this computer. Keep this window open; press Ctrl+C to stop.
"%AQC_PY_EXE%" %AQC_PY_SWITCH% -m aqc_app %*
set "AQC_EXIT_CODE=%ERRORLEVEL%"
if not "%AQC_EXIT_CODE%"=="0" (
    echo.
    echo AQC could not finish normally. The reason is shown above.
    echo For diagnostics, run: python scripts\doctor.py
    goto failed
)
popd
exit /b 0

:files_error
echo AQC: application files are missing.
echo Extract the complete repository/archive, then double-click start-aqc.cmd again.
goto failed

:folder_error
echo AQC: cannot open the extracted application folder.
if not defined AQC_NO_PAUSE pause
exit /b 2

:failed
popd
if not defined AQC_NO_PAUSE pause
exit /b %AQC_EXIT_CODE%
