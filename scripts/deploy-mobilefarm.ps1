#Requires -Version 5.1
<#
.SYNOPSIS
  Деплой links (FastAPI) на Mobile Farm — порт 8010.

.EXAMPLE
  .\scripts\deploy-mobilefarm.ps1
#>
[CmdletBinding()]
param(
    [string]$SshHost = "10.20.87.230",
    [string]$SshUser = "atom",
    [string]$IdentityFile = "",
    [string]$RemoteRoot = "/home/atom/links",
    [switch]$SkipBuild,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-DeployCommand([string]$Command, [switch]$AllowRobocopyCodes) {
    if ($DryRun) {
        Write-Host "[dry-run] $Command" -ForegroundColor DarkGray
        return
    }
    Invoke-Expression $Command
    if ($AllowRobocopyCodes) {
        if ($LASTEXITCODE -gt 7) { throw "Command failed ($LASTEXITCODE): $Command" }
        return
    }
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Command" }
}

function Resolve-IdentityFile([string]$Preferred) {
    if ($Preferred -and (Test-Path $Preferred)) { return $Preferred }
    foreach ($c in @(
            "$env:USERPROFILE\.ssh\id_ed25519",
            "$env:USERPROFILE\.ssh\id_rsa"
        )) {
        if (Test-Path $c) { return $c }
    }
    throw "SSH key not found. Run: ssh-copy-id ${SshUser}@${SshHost}"
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$staging = Join-Path $env:TEMP ("links-mobilefarm-{0}" -f [guid]::NewGuid().ToString("N"))
$remote = "${SshUser}@${SshHost}"
$IdentityFile = Resolve-IdentityFile $IdentityFile
$ssh = "ssh -i `"$IdentityFile`" -o BatchMode=yes -o ConnectTimeout=20 $remote"
$scp = "scp -i `"$IdentityFile`" -o BatchMode=yes"

$excludeDirs = @(".git", ".venv", "venv", "__pycache__", ".cursor")
$excludeFiles = @(".env", "*.mmdb", "*.pyc")

try {
    Write-Step "Source: $repoRoot"
    Write-Step "Target: ${remote}:${RemoteRoot}"
    New-Item -ItemType Directory -Path $staging -Force | Out-Null

    $xd = ($excludeDirs | ForEach-Object { "/XD", $_ }) -join " "
    $xf = ($excludeFiles | ForEach-Object { "/XF", $_ }) -join " "
    Invoke-DeployCommand "robocopy `"$repoRoot`" `"$staging`" /E /NFL /NDL /NJH /NJS /NC /NS $xd $xf" -AllowRobocopyCodes

    Write-Step "Upload to server (tarball)"
    $tarball = Join-Path $env:TEMP ("links-deploy-{0}.tgz" -f [guid]::NewGuid().ToString("N"))
    Push-Location $staging
    try {
        & tar -czf $tarball .
        if ($LASTEXITCODE -ne 0) { throw "tar failed ($LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
    $remoteTar = "/tmp/links-deploy.tgz"
    Invoke-DeployCommand "$ssh `"rm -rf '$RemoteRoot' && mkdir -p '$RemoteRoot'`""
    Invoke-DeployCommand "scp -i `"$IdentityFile`" -o BatchMode=yes `"$tarball`" ${remote}:${remoteTar}"
    Invoke-DeployCommand "$ssh `"tar -xzf ${remoteTar} -C '$RemoteRoot' && rm -f ${remoteTar}`""
    Remove-Item -Force $tarball -ErrorAction SilentlyContinue

    $buildFlag = if ($SkipBuild) { "" } else { " --build" }
    $remoteCmd = @"
set -e
cd '$RemoteRoot'
if [ ! -f .env ]; then
  POSTGRES_PASSWORD=`$(openssl rand -hex 24)
  SECRET_KEY=`$(openssl rand -hex 32)
  ADMIN_PASSWORD=`$(openssl rand -base64 18 | tr -d '=+/' | head -c 16)
  API_TOKEN=`$(openssl rand -hex 24)
  cat > .env <<EOF
POSTGRES_PASSWORD=`$POSTGRES_PASSWORD
SECRET_KEY=`$SECRET_KEY
ADMIN_PASSWORD=`$ADMIN_PASSWORD
API_TOKEN=`$API_TOKEN
SESSION_COOKIE_HTTPS_ONLY=false
EOF
  chmod 600 .env
  echo 'Created .env with generated secrets (saved on server only).'
fi
docker compose -f docker-compose.prod.yml up -d$buildFlag
docker compose -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:8010/health && echo ' health OK'
"@ -replace "`r`n", "`n"

    Write-Step "docker compose up"
    if ($DryRun) {
        Write-Host "[dry-run] remote deploy" -ForegroundColor DarkGray
    } else {
        $remoteCmd | & ssh -i $IdentityFile -o BatchMode=yes -o ConnectTimeout=20 "${SshUser}@${SshHost}" "bash -s"
        if ($LASTEXITCODE -ne 0) { throw "Remote deploy failed ($LASTEXITCODE)" }
    }

    Write-Step "Done: production https://bytl.org/  (Coolify on ${SshHost}:8102)"
    Write-Host "Admin password: see ADMIN_PASSWORD in .env on server ($RemoteRoot)." -ForegroundColor Yellow
} finally {
    if (Test-Path $staging) { Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue }
}
