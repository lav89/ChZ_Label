@echo off
rem Konvert PDF-vygruzok CHZ na otdelnye etikaletki (okno)
cd /d "%~dp0"
if not exist "win-embed\python.exe" (
  echo OSHIBKA: papka win-embed ne najdena. Raspakuite arhiv TSELICOM.
  pause
  exit /b 1
)
start "" win-embed\pythonw.exe -X utf8 "Bin\ChZ_Label_GUI.py"
