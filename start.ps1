$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
if (!(Test-Path '.venv')) { py -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe .\app.py
