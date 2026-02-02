# Universal backup script - Auto-detect 7-Zip, fallback to robocopy
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$projectName = (Get-Item .).Name
$backupDir = "D:\githv\bak"

if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
}

# Default exclude patterns
$defaultExcludes = @(
    @{ Name = ".git"; Type = "dir"; Enabled = $true },
    @{ Name = "__pycache__"; Type = "dir"; Enabled = $true },
    @{ Name = ".venv"; Type = "dir"; Enabled = $true },
    @{ Name = "venv"; Type = "dir"; Enabled = $true },
    @{ Name = "node_modules"; Type = "dir"; Enabled = $true },
    @{ Name = ".vscode"; Type = "dir"; Enabled = $true },
    @{ Name = ".idea"; Type = "dir"; Enabled = $true },
    @{ Name = "*.egg-info"; Type = "pattern"; Enabled = $true },
    @{ Name = "bak"; Type = "dir"; Enabled = $true },
    @{ Name = "*.pyc"; Type = "pattern"; Enabled = $true },
    @{ Name = "*.log"; Type = "pattern"; Enabled = $true }
)

function Show-Menu {
    Write-Host "`n[CONFIG] Select files/directories to EXCLUDE from backup:`n" -ForegroundColor Cyan

    for ($i = 0; $i -lt $defaultExcludes.Count; $i++) {
        $item = $defaultExcludes[$i]
        $status = if ($item.Enabled) { "[X]" } else { "[ ]" }
        $type = if ($item.Type -eq "dir") { "DIR " } else { "FILE" }
        $num = $i + 1
        Write-Host "  $num. $status $type $($item.Name)"
    }

    Write-Host "`nCommands: toggle <num>, select all, deselect all, start, cancel`n"
}

Show-Menu
$cmd = ""

do {
    $cmd = Read-Host -Prompt "Backup"

    if ($cmd -eq "cancel") {
        Write-Host "[CANCEL] Backup aborted.`n" -ForegroundColor Yellow
        exit
    }
    elseif ($cmd -eq "select all" -or $cmd -eq "sa") {
        $defaultExcludes | ForEach-Object { $_.Enabled = $true }
    }
    elseif ($cmd -eq "deselect all" -or $cmd -eq "da") {
        $defaultExcludes | ForEach-Object { $_.Enabled = $false }
    }
    elseif ($cmd -match "^toggle (\d+)$" -or $cmd -match "^t (\d+)$") {
        $idx = [int]$matches[1] - 1
        if ($idx -ge 0 -and $idx -lt $defaultExcludes.Count) {
            $defaultExcludes[$idx].Enabled = -not $defaultExcludes[$idx].Enabled
        }
    }
    elseif ($cmd -match "^\d+$") {
        $idx = [int]$cmd - 1
        if ($idx -ge 0 -and $idx -lt $defaultExcludes.Count) {
            $defaultExcludes[$idx].Enabled = -not $defaultExcludes[$idx].Enabled
        }
    }

    Show-Menu
} while ($cmd -ne "start" -and $cmd -ne "")

# Build exclude lists
$excludeDirs = $defaultExcludes | Where-Object { $_.Enabled -and $_.Type -eq "dir" } | ForEach-Object { $_.Name }
$excludePatterns = $defaultExcludes | Where-Object { $_.Enabled -and $_.Type -eq "pattern" } | ForEach-Object { $_.Name }

if ($excludeDirs.Count -gt 0 -or $excludePatterns.Count -gt 0) {
    Write-Host "[SKIP] Excluding: $($excludeDirs + $excludePatterns -join ', ')`n" -ForegroundColor Yellow
} else {
    Write-Host "[SKIP] No exclusions (backing up everything)`n" -ForegroundColor Yellow
}

# Find 7-Zip
$sevenZipPaths = @(
    "C:\Program Files\7-Zip\7z.exe",
    "C:\Program Files (x86)\7-Zip\7z.exe"
)
$sevenZip = $sevenZipPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($sevenZip) {
    $zipPath = "$backupDir\$($projectName)_$timestamp.zip"
    Write-Host "[INFO] Using 7-Zip...`n" -ForegroundColor Cyan

    $excludeArgs = @()
    foreach ($dir in $excludeDirs) {
        $excludeArgs += "-x!$dir"
    }
    foreach ($pattern in $excludePatterns) {
        $excludeArgs += "-x!$pattern"
    }

    & $sevenZip a -tzip -mx1 $zipPath @excludeArgs * | Out-Null

    $size = "{0:N2}" -f ((Get-Item $zipPath).Length / 1MB)
    Write-Host "`n[OK] $zipPath ($size MB)`n" -ForegroundColor Green
} else {
    $targetDir = "$backupDir\$($projectName)_$timestamp"
    Write-Host "[INFO] 7-Zip not found, using robocopy...`n" -ForegroundColor Cyan

    $xdArgs = $excludeDirs -join " "
    $xfArgs = ($excludePatterns | ForEach-Object { $_ -replace '\*', '' }) -join " "

    robocopy . $targetDir /E /XD $xdArgs /XF $xfArgs /NFL /NDL /NJH /NJS /NP /R:0 /W:0

    Write-Host "`n[OK] $targetDir`n" -ForegroundColor Green
}

Write-Host "`nDone. Press any key to exit..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
