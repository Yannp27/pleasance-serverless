<#
.SYNOPSIS
Start Antigravity Proxy + Cloudflare Tunnel for remote agent access

.DESCRIPTION
This script:
1. Starts the Antigravity Claude Proxy on port 8080
2. Creates a Cloudflare tunnel to expose it
3. Saves the tunnel URL for agent configuration

.USAGE
.\start-proxy-tunnel.ps1
#>

$ErrorActionPreference = "Stop"

Write-Host "=== Pleasance Agent Proxy Startup ===" -ForegroundColor Cyan
Write-Host ""

# Check if proxy is already running
$proxyRunning = $false
try {
    $health = Invoke-WebRequest -Uri "http://localhost:8080/health" -TimeoutSec 3 -ErrorAction SilentlyContinue
    if ($health.StatusCode -eq 200) {
        $proxyRunning = $true
        Write-Host "[OK] Proxy already running on port 8080" -ForegroundColor Green
    }
} catch {
    Write-Host "[INFO] Proxy not running, starting..." -ForegroundColor Yellow
}

# Start proxy if needed
if (-not $proxyRunning) {
    Write-Host "Starting Antigravity Claude Proxy..." -ForegroundColor Yellow
    
    # Start in new window
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "antigravity-claude-proxy start" -WindowStyle Normal
    
    # Wait for it to be ready
    $attempts = 0
    $maxAttempts = 30
    while ($attempts -lt $maxAttempts) {
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-WebRequest -Uri "http://localhost:8080/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($health.StatusCode -eq 200) {
                Write-Host "[OK] Proxy started successfully" -ForegroundColor Green
                break
            }
        } catch {}
        $attempts++
        Write-Host "." -NoNewline
    }
    
    if ($attempts -ge $maxAttempts) {
        Write-Host ""
        Write-Host "[ERROR] Proxy failed to start" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""

# Check if cloudflared is installed
$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflared) {
    Write-Host "[WARN] cloudflared not found. Install with:" -ForegroundColor Yellow
    Write-Host "  winget install cloudflare.cloudflared" -ForegroundColor White
    Write-Host ""
    Write-Host "After installing, re-run this script." -ForegroundColor Yellow
    exit 1
}

Write-Host "Starting Cloudflare Tunnel..." -ForegroundColor Yellow
Write-Host "(This exposes the proxy for remote RunPod agents)" -ForegroundColor DarkGray
Write-Host ""

# Start tunnel and capture URL
$tunnelJob = Start-Job -ScriptBlock {
    cloudflared tunnel --url http://localhost:8080 2>&1
}

# Wait for URL to appear in output
$tunnelUrl = $null
$attempts = 0
while ($attempts -lt 30 -and -not $tunnelUrl) {
    Start-Sleep -Seconds 1
    $output = Receive-Job $tunnelJob
    foreach ($line in $output) {
        if ($line -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
            $tunnelUrl = $matches[0]
            break
        }
    }
    $attempts++
}

if ($tunnelUrl) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host " TUNNEL URL (use as ANTHROPIC_BASE_URL)" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  $tunnelUrl" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    
    # Save to file for orchestrator
    $tunnelUrl | Out-File -FilePath "$PSScriptRoot\.tunnel_url" -Encoding UTF8
    Write-Host ""
    Write-Host "URL saved to: $PSScriptRoot\.tunnel_url" -ForegroundColor DarkGray
    
    # Copy to clipboard
    $tunnelUrl | Set-Clipboard
    Write-Host "URL copied to clipboard!" -ForegroundColor Green
    
} else {
    Write-Host "[ERROR] Could not get tunnel URL" -ForegroundColor Red
    Write-Host "Check cloudflared output manually" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Press Ctrl+C to stop the tunnel when done." -ForegroundColor DarkGray

# Keep script running (tunnel runs in background job)
try {
    while ($true) {
        Start-Sleep -Seconds 60
        # Check tunnel is still alive
        $state = Get-Job $tunnelJob.Id | Select-Object -ExpandProperty State
        if ($state -ne "Running") {
            Write-Host "[WARN] Tunnel stopped unexpectedly" -ForegroundColor Yellow
            break
        }
    }
} finally {
    Stop-Job $tunnelJob -ErrorAction SilentlyContinue
    Remove-Job $tunnelJob -ErrorAction SilentlyContinue
}
