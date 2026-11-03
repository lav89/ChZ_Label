@echo off
rem Generator DataMatrix (CHZ) - sozdanie etikalet PDF/PRN iz CSV
cd /d "%~dp0"
if not exist "win-embed\python.exe" (
  echo OSHIBKA: papka win-embed ne najdena. Raspakuite arhiv TSELICOM.
  pause
  exit /b 1
)
start "" win-embed\pythonw.exe -X utf8 "Bin\Generator_datamatrix.py"
