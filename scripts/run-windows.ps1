$ErrorActionPreference = "Stop"
if (-not (Test-Path .venv)) { py -3 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -U pip
& .\.venv\Scripts\python.exe -m pip install -e .
if (-not (Test-Path config.yml)) { Copy-Item config.example.yml config.yml }
& .\.venv\Scripts\od-rclone.exe
