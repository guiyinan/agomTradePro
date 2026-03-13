[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $ProjectRoot "deploy/.env.qlib-train"
$EnvExample = Join-Path $ProjectRoot "deploy/.env.qlib-train.example"
$ComposeFile = Join-Path $ProjectRoot "docker/docker-compose.qlib-train.yml"
$RuntimeData = Join-Path $ProjectRoot "runtime/qlib_data"
$RuntimeModels = Join-Path $ProjectRoot "runtime/qlib_models"

docker --version | Out-Null

if (-not (Test-Path $EnvFile)) {
    Copy-Item $EnvExample $EnvFile -Force
    Write-Host "[INFO] created $EnvFile from example"
    Write-Host "[INFO] review SECRET_KEY / DATABASE_URL / REDIS_URL before first real training run"
}

New-Item -ItemType Directory -Force $RuntimeData | Out-Null
New-Item -ItemType Directory -Force $RuntimeModels | Out-Null

docker compose -f $ComposeFile --env-file $EnvFile up -d --build

Write-Host "[INFO] qlib train runtime started"
Write-Host "[INFO] worker: agomsaaf_qlib_train_worker"
Write-Host "[INFO] logs: docker compose -f $ComposeFile --env-file $EnvFile logs -f"
