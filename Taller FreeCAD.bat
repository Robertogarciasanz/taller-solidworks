@echo off
cd /d "%~dp0freecad"
py -u taller_freecad.py
if errorlevel 1 pause
