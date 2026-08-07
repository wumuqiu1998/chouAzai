# Vibe-Research startup (Windows PowerShell)
# Usage:
#   .\start.ps1
#   .\start.ps1 -Install
#   .\start.ps1 -Cli claude

param(
    [switch]$Install,
    [string]$Cli = ""
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"
$VenvPip = Join-Path $Backend ".venv\Scripts\pip.exe"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

function Stop-PortListeners([int]$Port) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 500
    $ErrorActionPreference = $prev
}

function Test-PyImport([string]$Module) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    & $VenvPython -c "import $Module" 2>$null | Out-Null
    $ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prev
    return $ok
}

function Install-BackendDeps {
    Write-Step "Installing backend deps (first run may take several minutes)..."
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $VenvPip install -r (Join-Path $Backend "requirements.txt")
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($code -ne 0) {
        throw "pip install failed (exit $code). Try: cd backend; .\.venv\Scripts\pip install -r requirements.txt"
    }
}

function Ensure-Backend {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "python not found. Install Python 3.10+ and add it to PATH."
    }
    if (-not (Test-Path $VenvPython)) {
        Write-Step "Creating Python venv..."
        python -m venv (Join-Path $Backend ".venv")
    }
    if (-not (Test-Path $VenvPip)) {
        throw "Failed to create venv"
    }

    # pip show 在包缺失时会往 stderr 打 WARNING，PowerShell 5 + $ErrorActionPreference=Stop 会直接中断
    $needImport = @(
        @{ pip = "fastapi"; import = "fastapi" },
        @{ pip = "langgraph"; import = "langgraph" },
        @{ pip = "langchain-openai"; import = "langchain_openai" }
    )
    $missing = @($needImport | Where-Object { -not (Test-PyImport $_.import) })

    if ($Install -or $missing.Count -gt 0) {
        if ($missing.Count -gt 0 -and -not $Install) {
            Write-Host "Missing: $($missing.pip -join ', ')" -ForegroundColor DarkYellow
        }
        Install-BackendDeps
        $still = @($needImport | Where-Object { -not (Test-PyImport $_.import) })
        if ($still.Count -gt 0) {
            throw "Still missing after install: $($still.pip -join ', ')"
        }
    }
}

function Ensure-Frontend {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm not found. Install Node.js 18+."
    }
    if ($Install -or -not (Test-Path (Join-Path $Frontend "node_modules"))) {
        Write-Step "Installing frontend deps..."
        Push-Location $Frontend
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try { npm install } finally { $ErrorActionPreference = $prev; Pop-Location }
        if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    }
}

function Start-Backend {
    $envFile = Join-Path $Backend ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#") -and $line -match "^([^=]+)=(.*)$") {
                $k = $Matches[1].Trim()
                $v = $Matches[2].Trim().Trim('"').Trim("'")
                if (-not [string]::IsNullOrEmpty($k)) { Set-Item -Path "env:$k" -Value $v }
            }
        }
    }
    if ($Cli) { $env:VIBE_LLM_CLI = $Cli }

    # 未配置 API key 时，自动探测本机已登录的 CLI（与网页「接入 AI」无关，复盘走这条）
    if (-not $env:VIBE_LLM_CLI -and -not $env:OPENAI_API_KEY -and -not $env:VR_LLM_API_KEY -and -not $env:MIMO_API_KEY) {
        foreach ($kind in @("claude", "codex", "qwen", "deepseek")) {
            if (Get-Command $kind -ErrorAction SilentlyContinue) {
                $env:VIBE_LLM_CLI = $kind
                Write-Host "Auto-detected CLI: $kind (set VIBE_LLM_CLI in backend/.env to override)" -ForegroundColor DarkYellow
                break
            }
        }
    }

    Write-Step "Starting backend http://127.0.0.1:8900"
    $proc = Start-Process -FilePath $VenvPython `
        -ArgumentList @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8900") `
        -WorkingDirectory $Backend `
        -PassThru `
        -WindowStyle Minimized
    return $proc
}

function Wait-Backend($proc, $seconds = 60) {
    $url = "http://127.0.0.1:8900/api/health"
    for ($i = 0; $i -lt $seconds; $i++) {
        if ($proc.HasExited) {
            throw "Backend exited early (code $($proc.ExitCode)). Run: cd backend; .\.venv\Scripts\python -m uvicorn app:app --port 8900"
        }
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { return $true }
        } catch { Start-Sleep -Seconds 1 }
    }
    if ($proc.HasExited) {
        throw "Backend crashed. Run backend manually to see the error."
    }
    throw "Backend health check timed out after ${seconds}s."
}

Write-Host @"

  Vibe-Research
  Backend :8900  |  Frontend :5899  |  http://localhost:5899

"@ -ForegroundColor Yellow

Ensure-Backend
Ensure-Frontend
Stop-PortListeners 8900
Stop-PortListeners 5899
$backendProc = Start-Backend
Wait-Backend $backendProc | Out-Null

Write-Step "Starting frontend http://localhost:5899 (Ctrl+C stops both)"
Write-Host "Short-term review: sidebar -> review board`n" -ForegroundColor DarkGray

Push-Location $Frontend
try {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    npm run dev
} finally {
    $ErrorActionPreference = $prev
    Pop-Location
    if ($backendProc -and -not $backendProc.HasExited) {
        Write-Step "Stopping backend..."
        Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
    }
}
