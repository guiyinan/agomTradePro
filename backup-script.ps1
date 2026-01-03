# Quick backup script - Auto-detect 7-Zip, fallback to robocopy
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = "D:\githv\bak"

if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
}

# Find 7-Zip
$sevenZipPaths = @(
    "C:\Program Files\7-Zip\7z.exe",
    "C:\Program Files (x86)\7-Zip\7z.exe"
)
$sevenZip = $sevenZipPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($sevenZip) {
    # Use 7-Zip
    $zipPath = "$backupDir\agomSAAF_$timestamp.zip"
    Write-Host "Using 7-Zip..." -ForegroundColor Cyan

    $excludeArgs = @(
        "-x!.git", "-x!__pycache__", "-x!.venv", "-x!venv",
        "-x!node_modules", "-x!.vscode", "-x!.idea",
        "-x!*.egg-info", "-x!bak"
    )

    & $sevenZip a -tzip -mx1 $zipPath @excludeArgs * | Out-Null

    $size = "{0:N2}" -f ((Get-Item $zipPath).Length / 1MB)
    Write-Host "Done: $zipPath ($size MB)" -ForegroundColor Green
} else {
    # Fallback to robocopy mirror
    $targetDir = "$backupDir\agomSAAF_$timestamp"
    Write-Host "7-Zip not found, using robocopy..." -ForegroundColor Cyan
    Write-Host "Mirroring to: $targetDir"

    robocopy . $targetDir /E /XD .git __pycache__ .venv venv node_modules .vscode .idea bak /XF *.pyc *.log /NFL /NDL /NJH /NJS /NP /R:0 /W:0

    Write-Host "Done: $targetDir" -ForegroundColor Green
}
