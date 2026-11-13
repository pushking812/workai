<#
  Shared helper (dot-source it): starts its own Excel, waits until COM answers, closes only that Excel.

  . "$PSScriptRoot\excel_session.ps1"
  $s = Start-ExcelSession            # refuses to run if a user's Excel is already open (use -AllowRunning to override)
  $xl = $s.App
  ...
  Stop-ExcelSession $s
#>

function Start-ExcelSession {
    param(
        [int]$StartTimeoutSec = 60,
        [switch]$AllowRunning
    )
    $before = @(Get-Process -Name EXCEL -ErrorAction SilentlyContinue)
    if ($before.Count -gt 0 -and -not $AllowRunning) {
        throw "Excel is already running (pid " + (($before | ForEach-Object { $_.Id }) -join ",") + "). Close it or pass -AllowRunning; the script will not touch it."
    }
    $beforeIds = @($before | ForEach-Object { $_.Id })

    # /x = separate instance, /e = no splash screen and no empty book
    $proc = Start-Process -FilePath "excel.exe" -ArgumentList "/x", "/e" -PassThru
    $deadline = (Get-Date).AddSeconds($StartTimeoutSec)
    $ownPid = 0
    while ((Get-Date) -lt $deadline -and $ownPid -eq 0) {
        Start-Sleep -Milliseconds 500
        $new = @(Get-Process -Name EXCEL -ErrorAction SilentlyContinue | Where-Object { $beforeIds -notcontains $_.Id })
        if ($new.Count -gt 0) { $ownPid = $new[0].Id }
    }
    if ($ownPid -eq 0) { throw "Excel did not start within $StartTimeoutSec s" }

    # Wait until the instance is registered and accepts calls ("Call was rejected" while it starts).
    $xl = $null
    $lastErr = ""
    while ((Get-Date) -lt $deadline -and $null -eq $xl) {
        try {
            $cand = [System.Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")
            [void]$cand.Hwnd   # a call that fails while Excel is busy
            $xl = $cand
        } catch {
            $lastErr = $_.Exception.Message
            Start-Sleep -Milliseconds 700
        }
    }
    if ($null -eq $xl) {
        Stop-Process -Id $ownPid -Force -ErrorAction SilentlyContinue
        throw "Excel started but COM did not answer: $lastErr"
    }
    # Make sure this is our instance, not a user's one (only possible with -AllowRunning).
    $hwndPid = 0
    Add-Type -Namespace Win -Name NativeSess -MemberDefinition @"
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern int GetWindowThreadProcessId(System.IntPtr hWnd, out int pid);
"@ -ErrorAction SilentlyContinue
    [void][Win.NativeSess]::GetWindowThreadProcessId([System.IntPtr]$xl.Hwnd, [ref]$hwndPid)
    if ($hwndPid -gt 0) { $ownPid = $hwndPid }

    $xl.Visible = $false
    $xl.DisplayAlerts = $false
    return [pscustomobject]@{ App = $xl; Pid = $ownPid }
}

function Stop-ExcelSession {
    param($Session)
    if ($null -eq $Session) { return }
    try { $Session.App.Quit() } catch { }
    try { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($Session.App) } catch { }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
    # Normal quit first, kill only our own process if it is still alive after 10 s.
    $p = Get-Process -Id $Session.Pid -ErrorAction SilentlyContinue
    if ($p) {
        if (-not $p.WaitForExit(10000)) { Stop-Process -Id $Session.Pid -Force -ErrorAction SilentlyContinue }
    }
}
