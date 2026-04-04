$i = 0
while ($i -lt 10) {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:1200/" -UseBasicParsing -TimeoutSec 3 | Out-Null
        Write-Output "RSSHub is UP"
        break
    } catch {
        Write-Output "Waiting... ($i)"
        Start-Sleep 2
        $i++
    }
}
if ($i -eq 10) {
    Write-Output "RSSHub did not start"
    exit 1
}
