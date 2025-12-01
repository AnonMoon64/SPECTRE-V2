@echo off
REM Wrapper to run the Python screenshot plugin script from plugins/bin
SET SCRIPT_DIR=%~dp0
REM Resolve repo root (one level up from plugins\bin)
SET REPO_ROOT=%~dp0\..\..
python "%REPO_ROOT%examples\screenshot_plugin.py" %*
