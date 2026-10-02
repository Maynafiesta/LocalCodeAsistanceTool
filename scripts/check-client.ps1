param([string]$ConfigPath = (Join-Path $PSScriptRoot "config.yaml"))
$ErrorActionPreference = "Stop"
$configText = Get-Content -LiteralPath $ConfigPath -Raw
$baseMatch = [regex]::Match($configText, '(?m)^\s*apiBase:\s*("[^"\r\n]+")\s*$')
$authMatch = [regex]::Match($configText, '(?m)^\s*Authorization:\s*("[^"\r\n]+")\s*$')
if (-not $baseMatch.Success -or -not $authMatch.Success) {
    throw "Use the generated laptop config.yaml."
}
$serverUrl = ($baseMatch.Groups[1].Value | ConvertFrom-Json).TrimEnd('/')
$requestHeaders = @{ Authorization = ($authMatch.Groups[1].Value | ConvertFrom-Json) }
Write-Host "Server: $serverUrl"
$live = Invoke-RestMethod -Uri "$serverUrl/health/live" -TimeoutSec 10
if ($live.status -ne "ok") { throw "Server health check failed" }
Write-Host "LAN HTTP connection: OK"
$ready = Invoke-RestMethod -Uri "$serverUrl/health/ready" -Headers $requestHeaders -TimeoutSec 15
if ($ready.status -ne "ready") { throw "Models are not ready" }
Write-Host "Client credentials and model readiness: OK"
$completionPayload = @{
    model = "qwen2.5-coder:1.5b-base"
    stream = $false
    prompt = "// Return the sum of two integers.`nint add(int a, int b) {`n    return "
    suffix = ";`n}`n`nint subtract(int a, int b) {`n    return a - b;`n}`n"
    options = @{ temperature = 0; num_predict = 32 }
} | ConvertTo-Json -Depth 6
$completion = Invoke-RestMethod -Uri "$serverUrl/api/generate" -Method Post `
    -Headers $requestHeaders -ContentType "application/json" -Body $completionPayload -TimeoutSec 150
if (-not $completion.done -or -not $completion.response) { throw "No completion received" }
Write-Host "Completion: OK -> $($completion.response)"
$chatPayload = @{
    model = "qwen2.5-coder:7b-instruct-q4_K_M"
    stream = $false
    messages = @(@{ role = "user"; content = "In C++14, write a function adding two integers. Return only code." })
    options = @{ temperature = 0; num_predict = 128 }
} | ConvertTo-Json -Depth 6
$chat = Invoke-RestMethod -Uri "$serverUrl/api/chat" -Method Post `
    -Headers $requestHeaders -ContentType "application/json" -Body $chatPayload -TimeoutSec 150
if (-not $chat.done -or -not $chat.message.content) { throw "No chat answer received" }
Write-Host "Chat: OK"
Write-Host $chat.message.content
Write-Host "Client API checks passed. Next, test chat and inline completion in Continue."
