@echo off
rem Konsolnyi konvert: peretaishchite PDF-fayly na etot fayl
cd /d "%~dp0"
win-embed\python.exe -X utf8 "Bin\ChZ_Label_Convert.py" %*
if errorlevel 1 pause
