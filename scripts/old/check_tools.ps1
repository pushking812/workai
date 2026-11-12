param(
    [string]$BaseUrl = "http://127.0.0.1:8737"
)

$endpoints = @("/health", "/workspace", "/models", "/doctor")
$failed = 0

foreach ($ep in $endpoints) {
    $url = $BaseUrl.TrimEnd("/") + $ep
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
        Write-Host ("OK   {0}  ->  HTTP {1}" -f $ep, $r.StatusCode) -ForegroundColor Green
        Write-Host ("     " + $r.Content.Substring(0, [Math]::Min(200, $r.Content.Length)))
    }
    catch {
        $failed++
        Write-Host ("FAIL {0}  ->  {1}" -f $ep, $_.Exception.Message) -ForegroundColor Red
    }
}

if ($failed -eq 0) {
    Write-Host "Сервер ask доступен, все проверки пройдены." -ForegroundColor Green
    exit 0
}
else {
    Write-Host "Не прошло проверок: $failed. Проверьте, запущен ли сервер и верен ли -BaseUrl." -ForegroundColor Yellow
    exit 1
}