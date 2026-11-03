@echo off
cd /d "%~dp0"
win-embed\python.exe -X utf8 "Bin\Generator_datamatrix.py" %*
if errorlevel 1 pause
