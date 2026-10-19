# Builds the Windows x64 runtime executable consumed by the Electron app.
# Usage (from the repository root, Windows, Python 3.12 in PATH):
#   powershell -ExecutionPolicy Bypass -File services/agent-runtime/build-runtime.ps1
$ErrorActionPreference = "Stop"
$runtime = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $runtime
try {
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt "pyinstaller==6.11.1"
    if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependencias" }
    python -m PyInstaller --noconfirm --clean JARVIS-Agent-Runtime.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }
    $exe = Join-Path $runtime "dist/jarvis-agent-runtime/jarvis-agent-runtime.exe"
    if (-not (Test-Path $exe)) { throw "Executavel nao gerado: $exe" }
    $hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
    "$hash  jarvis-agent-runtime.exe" | Out-File -Encoding ascii (Join-Path $runtime "dist/SHA256SUMS-runtime.txt")
    Write-Host "OK: $exe"
    Write-Host "SHA256: $hash"
}
finally {
    Pop-Location
}
