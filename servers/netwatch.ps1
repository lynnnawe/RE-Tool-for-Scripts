$ErrorActionPreference = "SilentlyContinue"
$out = "$HOME\Downloads\potassium_netlog.txt"
$watchNames = @("Potassium", "RobloxPlayerBeta", "RobloxPlayerBeta.exe")
$seen = @{}
$dnsCache = @{}

function Resolve-Host($ip) {
    if ($dnsCache.ContainsKey($ip)) { return $dnsCache[$ip] }
    $name = "?"
    try { $name = [System.Net.Dns]::GetHostEntry($ip).HostName } catch { $name = "(no PTR)" }
    $dnsCache[$ip] = $name
    return $name
}

"Potassium network watch  --  $(Get-Date)" | Out-File $out
"Format:  process  PID  ->  remoteIP:port  (resolved host)" | Out-File $out -Append
"=========================================================" | Out-File $out -Append

Write-Host ""
Write-Host "  Watching for 150 seconds. >>> GO: launch Potassium now, log in, use it. <<<"
Write-Host "  Logging to $out"
Write-Host "  (Ctrl+C to stop early.)"
Write-Host ""

$end = (Get-Date).AddSeconds(150)
while ((Get-Date) -lt $end) {
    $procs = Get-Process | Where-Object { $watchNames -contains $_.ProcessName }
    foreach ($p in $procs) {
        $conns = Get-NetTCPConnection -OwningProcess $p.Id -ErrorAction SilentlyContinue |
                 Where-Object { $_.RemoteAddress -and $_.RemoteAddress -ne "0.0.0.0" -and $_.RemoteAddress -ne "127.0.0.1" -and $_.RemoteAddress -ne "::" -and $_.RemoteAddress -ne "::1" }
        foreach ($c in $conns) {
            $key = "$($p.ProcessName)|$($c.RemoteAddress)|$($c.RemotePort)"
            if (-not $seen.ContainsKey($key)) {
                $seen[$key] = $true
                $rhost = Resolve-Host $c.RemoteAddress
                $line = "{0,-20} pid={1,-6} -> {2}:{3}   ({4})" -f $p.ProcessName, $p.Id, $c.RemoteAddress, $c.RemotePort, $rhost
                $line | Out-File $out -Append
                Write-Host "  $line"
            }
        }
    }
    Start-Sleep -Milliseconds 400
}

"" | Out-File $out -Append
"=== DNS cache entries for relevant domains (what names were looked up) ===" | Out-File $out -Append
Get-DnsClientCache -ErrorAction SilentlyContinue |
    Where-Object { $_.Entry -match "potassium|roblox|kewl|vynixius|sirius|luarmor|cloudfront|amazonaws|fastly|cdn" } |
    Select-Object Entry, Data | Format-Table -AutoSize | Out-String | Out-File $out -Append

Write-Host ""
Write-Host "  Done. Send me this file:  $out"
