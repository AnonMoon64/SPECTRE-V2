@echo off
REM Append all arguments to a file for testing
set OUT=%~dp0echo_out.txt
echo %* >> "%OUT%"
exit /b 0
