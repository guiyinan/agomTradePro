param(
    [string]$TaskName = "AgomSAAF-Daily-Macro-Sync"
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "UNREGISTERED=$TaskName"
} else {
    Write-Output "NOT_FOUND=$TaskName"
}
