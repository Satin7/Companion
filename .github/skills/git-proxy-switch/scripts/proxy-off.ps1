<#
.SYNOPSIS
    Disable Git proxy for direct GitHub access.
.DESCRIPTION
    Unsets Git global HTTP/HTTPS proxy settings.
    Use this when you have direct access to GitHub without a proxy.
.EXAMPLE
    .\proxy-off.ps1
#>

Write-Host "🔌 Disabling Git proxy..." -ForegroundColor Cyan
git config --global --unset http.proxy 2>$null
git config --global --unset https.proxy 2>$null

Write-Host "✅ Git proxy is now OFF (direct connection)" -ForegroundColor Green
Write-Host ""
Write-Host "Current proxy config:" -ForegroundColor Yellow
$currentProxy = git config --global --get http.proxy 2>$null
if ($currentProxy) {
    Write-Host "http.proxy = $currentProxy" -ForegroundColor Red
} else {
    Write-Host "http.proxy = (not set)" -ForegroundColor Green
}
$currentHttpsProxy = git config --global --get https.proxy 2>$null
if ($currentHttpsProxy) {
    Write-Host "https.proxy = $currentHttpsProxy" -ForegroundColor Red
} else {
    Write-Host "https.proxy = (not set)" -ForegroundColor Green
}
