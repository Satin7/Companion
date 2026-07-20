<#
.SYNOPSIS
    Enable Git proxy for GitHub operations.
.DESCRIPTION
    Sets Git global HTTP/HTTPS proxy to the configured proxy server.
    Use this when you need to access GitHub through a proxy.
.EXAMPLE
    .\proxy-on.ps1
#>

$proxyHost = "127.0.0.1"
$proxyPort = "7897"
$proxyUrl = "http://${proxyHost}:${proxyPort}"

Write-Host "🔌 Enabling Git proxy..." -ForegroundColor Cyan
git config --global http.proxy $proxyUrl
git config --global https.proxy $proxyUrl

Write-Host "✅ Git proxy is now ON: $proxyUrl" -ForegroundColor Green
Write-Host ""
Write-Host "Current proxy config:" -ForegroundColor Yellow
git config --global --get http.proxy
git config --global --get https.proxy
