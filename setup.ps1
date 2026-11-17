$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# Vietnamese labels/output must not crash on a non-UTF-8 console.
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host '== Tool nha dat: bootstrap ==' -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Khong tim thay Python. Cai Python 3.10+ va chay lai setup.ps1.'
}

Write-Host "Python: $(python --version)"

$Venv = Join-Path $ProjectRoot '.venv'
if (-not (Test-Path $Venv)) {
    python -m venv $Venv
}

$VenvPython = Join-Path $Venv 'Scripts\python.exe'
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $ProjectRoot 'requirements.txt')

Write-Host '== Cai Chromium cho Playwright ==' -ForegroundColor Cyan
& $VenvPython -m playwright install chromium

# Register the Playwright MCP server for Claude Code in this project.
if (Get-Command claude -ErrorAction SilentlyContinue) {
    $Existing = (claude mcp list 2>$null) -join "`n"
    if ($Existing -match '(?m)^playwright:') {
        Write-Host 'Playwright MCP da duoc cau hinh, bo qua.'
    } else {
        Write-Host '== Dang ky Playwright MCP ==' -ForegroundColor Cyan
        $Profile = Join-Path $ProjectRoot 'Temp\browser-profile'
        claude mcp add playwright -- npx -y '@playwright/mcp@0.0.85' --browser chromium --user-data-dir $Profile
    }
} else {
    Write-Warning 'Khong tim thay claude CLI. Bo qua dang ky Playwright MCP; xem README de cau hinh thu cong.'
}

$SmokeOutput = Join-Path $ProjectRoot 'Temp\smoke-test.xlsx'
& $VenvPython -m src.property_tool.cli 'https://example.com' --output $SmokeOutput

Write-Host ''
Write-Host 'Cai dat thanh cong.' -ForegroundColor Green
Write-Host "Python environment: $VenvPython"
Write-Host "Smoke test: $SmokeOutput"
Write-Host ''
Write-Host 'Kiem tra lai MCP:'
Write-Host '  claude mcp list'
Write-Host ''
Write-Host 'Chay tool:'
Write-Host "  & '.\.venv\Scripts\python.exe' -m src.property_tool.cli --urls-file urls.txt --output research\jobs\property-data.xlsx"