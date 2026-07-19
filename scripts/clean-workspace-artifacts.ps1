[CmdletBinding(SupportsShouldProcess)]
param()

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TempPath = Join-Path $ProjectRoot "tmp"
$RemovedFiles = 0

foreach ($Pattern in @("test_db_*.sqlite3", "tmp_tui_*.log", "*.stackdump")) {
    foreach ($File in Get-ChildItem -LiteralPath $ProjectRoot -File -Filter $Pattern -ErrorAction SilentlyContinue) {
        if ($PSCmdlet.ShouldProcess($File.FullName, "Remove generated workspace artifact")) {
            Remove-Item -LiteralPath $File.FullName -Force
            $RemovedFiles += 1
        }
    }
}

if (Test-Path -LiteralPath $TempPath) {
    $ResolvedTempPath = (Resolve-Path -LiteralPath $TempPath).Path
    $ExpectedPrefix = $ProjectRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $ResolvedTempPath.StartsWith($ExpectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a temp directory outside the project root: $ResolvedTempPath"
    }
    if ($PSCmdlet.ShouldProcess($ResolvedTempPath, "Remove generated workspace temp directory")) {
        Remove-Item -LiteralPath $ResolvedTempPath -Recurse -Force
    }
}

Write-Output "Removed $RemovedFiles root artifact file(s)."
