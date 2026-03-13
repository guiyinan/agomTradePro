[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $ProjectRoot "deploy/.env.qlib-train"
$ComposeFile = Join-Path $ProjectRoot "docker/docker-compose.qlib-train.yml"

docker compose -f $ComposeFile --env-file $EnvFile down

Write-Host "[INFO] qlib train runtime stopped"
