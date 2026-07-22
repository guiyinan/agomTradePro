param(
    [string]$Version = "0.1.0",
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $RepoRoot "artifacts\qmt-agent"
}
$ResolvedOutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$TempParent = Join-Path $RepoRoot "tmp"
$StagingRoot = Join-Path $TempParent ("qmt-agent-package-" + [guid]::NewGuid().ToString("N"))
$ExpectedTempPrefix = [System.IO.Path]::GetFullPath($TempParent).TrimEnd("\") + "\"
if (-not ([System.IO.Path]::GetFullPath($StagingRoot).StartsWith($ExpectedTempPrefix, [System.StringComparison]::OrdinalIgnoreCase))) {
    throw "Unsafe package staging path: $StagingRoot"
}

New-Item -ItemType Directory -Force -Path $ResolvedOutputRoot | Out-Null
New-Item -ItemType Directory -Force -Path $StagingRoot | Out-Null
try {
    $StagedAgent = Join-Path $StagingRoot "qmt_agent"
    New-Item -ItemType Directory -Force -Path $StagedAgent | Out-Null
    Copy-Item -Path (Join-Path $RepoRoot "qmt_agent\*") -Destination $StagedAgent -Recurse -Force
    Get-ChildItem -LiteralPath (Join-Path $RepoRoot "qmt_agent\package") -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $StagingRoot $_.Name) -Force
    }
    Copy-Item -LiteralPath (Join-Path $RepoRoot "qmt_agent\README.md") -Destination (Join-Path $StagingRoot "README.md") -Force
    $DocsRoot = Join-Path $StagingRoot "docs"
    New-Item -ItemType Directory -Force -Path $DocsRoot | Out-Null
    Copy-Item -LiteralPath (Join-Path $RepoRoot "docs\operations\qmt-agent-local-install-package.md") -Destination $DocsRoot -Force
    Copy-Item -LiteralPath (Join-Path $RepoRoot "docs\operations\qmt-agent-runbook.md") -Destination $DocsRoot -Force

    Get-ChildItem -LiteralPath $StagingRoot -Directory -Recurse -Filter "__pycache__" | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
    }
    Get-ChildItem -LiteralPath $StagingRoot -File -Recurse | Where-Object {
        $_.Extension -in @(".pyc", ".pyo")
    } | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force
    }

    $Lock = Get-Content -LiteralPath (Join-Path $RepoRoot "qmt_agent\xtquant-lock.json") -Raw | ConvertFrom-Json
    $ManifestFiles = @(Get-ChildItem -LiteralPath $StagingRoot -File -Recurse | Sort-Object FullName | ForEach-Object {
        [ordered]@{
            path = $_.FullName.Substring($StagingRoot.Length + 1).Replace("\", "/")
            size = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    })
    if ($ManifestFiles.Count -lt 10) {
        throw "Package staging is incomplete; only $($ManifestFiles.Count) files were found."
    }
    $Manifest = [ordered]@{
        package = "agom-qmt-agent-windows"
        version = $Version
        built_at = [DateTime]::UtcNow.ToString("o")
        contains_secrets = $false
        contains_qmt = $false
        contains_xtquant_wheel = $false
        xtquant_lock = [ordered]@{ version = $Lock.version; sha256 = $Lock.sha256; source = $Lock.source }
        files = $ManifestFiles
    }
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
        (Join-Path $StagingRoot "manifest.json"),
        ($Manifest | ConvertTo-Json -Depth 8),
        $Utf8NoBom
    )

    $ZipPath = Join-Path $ResolvedOutputRoot "agom-qmt-agent-windows-$Version.zip"
    if (Test-Path -LiteralPath $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $StagingRoot,
        $ZipPath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )
    $ZipHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    [System.IO.File]::WriteAllText("$ZipPath.sha256", "$ZipHash  $([System.IO.Path]::GetFileName($ZipPath))`n", $Utf8NoBom)
    Write-Host "Package: $ZipPath"
    Write-Host "SHA-256: $ZipHash"
}
finally {
    $ResolvedStaging = [System.IO.Path]::GetFullPath($StagingRoot)
    if ($ResolvedStaging.StartsWith($ExpectedTempPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $ResolvedStaging)) {
        Remove-Item -LiteralPath $ResolvedStaging -Recurse -Force
    }
}
