# One-command startup (Windows):  powershell -ExecutionPolicy Bypass -File .\start.ps1
# Installs what is missing, then opens the backend (port 8000) and frontend (port 5173) in two windows.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$py = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Creating backend virtual environment..."
    python -m venv (Join-Path $backend ".venv")
}
Write-Host "Checking backend packages..."
& $py -m pip install -q --disable-pip-version-check -r (Join-Path $backend "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "Installing frontend packages..."
    Push-Location $frontend
    try { npm install; if ($LASTEXITCODE -ne 0) { throw "npm install failed" } } finally { Pop-Location }
}

$envFile = Join-Path $backend ".env"
if (-not (Test-Path $envFile)) {
    Write-Warning "backend\.env not found: using defaults. Copy backend\.env.example to backend\.env to configure."
}
$dbOverride = $env:DATABASE_PATH
if (-not $dbOverride -and (Test-Path $envFile)) {
    $dbOverride = (Select-String -Path $envFile -Pattern '^\s*DATABASE_PATH\s*=\s*\S' -Quiet)
}
if ($root -match "OneDrive" -and -not $dbOverride) {
    Write-Warning "This folder is inside OneDrive. Set DATABASE_PATH in backend\.env to a folder outside it (e.g. C:/pickupbox/pickup_box.db)."
}

Start-Process powershell -WorkingDirectory $backend -ArgumentList @(
    "-NoExit", "-Command",
    "`$Host.UI.RawUI.WindowTitle = 'Pickup Box backend :8000'; & '$py' -m uvicorn main:app --host 0.0.0.0 --port 8000"
)
Start-Process powershell -WorkingDirectory $frontend -ArgumentList @(
    "-NoExit", "-Command",
    "`$Host.UI.RawUI.WindowTitle = 'Pickup Box frontend :5173'; npm run dev"
)

$ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.InterfaceAlias -notmatch 'vEthernet|Loopback|VirtualBox|VMware' } |
    Select-Object -First 1 -ExpandProperty IPAddress
if (-not $ip) { $ip = "<this-laptop-LAN-IP>" }

Write-Host ""
Write-Host "Started in two new windows (close them to stop)."
Write-Host "  On this laptop:   http://127.0.0.1:5173/          (links to everything)"
Write-Host "  Simulator:        http://${ip}:5173/simulator"
Write-Host "  Courier codes:    http://127.0.0.1:5173/courier   (demo only)"
Write-Host "  Box screens:      http://${ip}:5173/screen/BOX-01  and  /screen/BOX-02"
Write-Host "  NFC tag URLs:     http://${ip}:5173/pickup/BOX-01  and  /pickup/BOX-02"
Write-Host "  API docs:         http://${ip}:8000/docs"
Write-Host "  Bridge:           set API_BASE_URL=http://${ip}:8000"
