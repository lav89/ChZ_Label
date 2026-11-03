@echo off
cd /d "%~dp0"
win-embed\python.exe -X utf8 "Bin\gui_printer_port.py" %*
if errorlevel 1 pause
