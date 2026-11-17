# Ubuntu Line - one-command Android SMS gateway setup (Windows PowerShell)
# Run:  powershell -ExecutionPolicy Bypass -File setup_gateway.ps1 [-TestNumber +27XXXXXXXXX]
param([string]$TestNumber = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Fail($msg) { Write-Host "FAIL: $msg" -ForegroundColor Red; exit 1 }
function Ok($msg) { Write-Host "OK:   $msg" -ForegroundColor Green }

# 1. Read .env
if (-not (Test-Path .env)) { Fail ".env not found. Run: copy .env.example .env  then fill it in." }
$cfg = @{}
foreach ($line in Get-Content .env) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $k, $v = $line -split '=', 2
    $cfg[$k.Trim()] = $v.Trim().Trim('"')
}
foreach ($k in 'GEMINI_API_KEY', 'SMSGATE_USER', 'SMSGATE_PASS') {
    if (-not $cfg[$k]) { Fail "$k is empty in .env" }
}
Ok ".env has Gemini + gateway credentials"

# 2. Dependencies + tests
python -m pip install -q -r requirements.txt
if ($LASTEXITCODE) { Fail "pip install failed" }
python simulate.py
if ($LASTEXITCODE) { Fail "simulate.py tests failed" }
Ok "tests passed"

# 3. ngrok present?
if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    Fail "ngrok not installed. Run: winget install ngrok.ngrok   then: ngrok config add-authtoken YOUR_TOKEN (from dashboard.ngrok.com)"
}

# 4. Start app + ngrok in their own windows (keep both open for the demo)
Start-Process python -ArgumentList 'app.py' -WorkingDirectory $PSScriptRoot
Start-Process ngrok -ArgumentList 'http', '5000'
$url = $null
for ($i = 0; $i -lt 25 -and -not $url; $i++) {
    Start-Sleep -Seconds 1
    try {
        $t = Invoke-RestMethod http://127.0.0.1:4040/api/tunnels
        $url = ($t.tunnels | Where-Object { $_.public_url -like 'https*' } | Select-Object -First 1).public_url
    } catch {}
}
if (-not $url) { Fail "ngrok tunnel did not start (check the ngrok window; authtoken set?)" }
Ok "public URL: $url"

try { Invoke-RestMethod http://127.0.0.1:5000/log | Out-Null; Ok "app running on port 5000" }
catch { Fail "app not responding on port 5000 (check the python window)" }

# 5. Register webhook with sms-gate.app (remove old sms:received hooks first)
$api = 'https://api.sms-gate.app/3rdparty/v1'
$auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$($cfg.SMSGATE_USER):$($cfg.SMSGATE_PASS)"))
$h = @{ Authorization = "Basic $auth" }
try {
    foreach ($w in @(Invoke-RestMethod "$api/webhooks" -Headers $h)) {
        if ($w.id -and $w.event -eq 'sms:received') {
            Invoke-RestMethod "$api/webhooks/$($w.id)" -Method Delete -Headers $h | Out-Null
        }
    }
    $body = @{ url = "$url/sms-gate"; event = 'sms:received' } | ConvertTo-Json
    $hook = Invoke-RestMethod "$api/webhooks" -Method Post -Headers $h -ContentType 'application/json' -Body $body
} catch { Fail "sms-gate API error (wrong SMSGATE_USER/PASS, or Cloud Server off in the app): $($_.Exception.Message)" }
Ok "webhook registered -> $url/sms-gate"

# 6. Optional outbound test
if ($TestNumber) {
    $msg = @{ textMessage = @{ text = 'Ubuntu Line test: gateway connected.' }; phoneNumbers = @($TestNumber) } | ConvertTo-Json -Depth 3
    try { Invoke-RestMethod "$api/messages" -Method Post -Headers $h -ContentType 'application/json' -Body $msg | Out-Null; Ok "test SMS queued to $TestNumber" }
    catch { Fail "could not send test SMS: $($_.Exception.Message)" }
}

Write-Host ""
Write-Host "READY. SMS 'hi' to the gateway phone and watch http://127.0.0.1:5000" -ForegroundColor Cyan
Write-Host "Keep the python + ngrok windows open. If ngrok restarts, run this script again."
