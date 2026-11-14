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
    # An Excel that a previous script has just closed may still be shutting down: give it a few seconds.
    $wait = (Get-Date).AddSeconds(12)
    while ($before.Count -gt 0 -and -not $AllowRunning -and (Get-Date) -lt $wait) {
        Start-Sleep -Milliseconds 700
        $before = @(Get-Process -Name EXCEL -ErrorAction SilentlyContinue)
    }
    if ($before.Count -gt 0 -and -not $AllowRunning) {
        throw "Excel is already running (pid " + (($before | ForEach-Object { $_.Id }) -join ",") + "). Close it or pass -AllowRunning; the script will not touch it."
    }
    $beforeIds = @($before | ForEach-Object { $_.Id })

    # Create our own instance directly through COM. The old way (excel.exe /x + GetActiveObject)
    # waited for the window to get focus: a /x instance registers itself in the running object
    # table only when it is activated, so the script hung until the user switched to Excel.
    $deadline = (Get-Date).AddSeconds($StartTimeoutSec)
    $xl = $null
    $lastErr = ""
    while ((Get-Date) -lt $deadline -and $null -eq $xl) {
        try {
            $cand = New-Object -ComObject Excel.Application
            [void]$cand.Hwnd   # a call that fails while Excel is busy
            $xl = $cand
        } catch {
            $lastErr = $_.Exception.Message
            Start-Sleep -Milliseconds 700
        }
    }
    if ($null -eq $xl) { throw "Excel did not start via COM within $StartTimeoutSec s: $lastErr" }
    $xl.Visible = $false
    $xl.DisplayAlerts = $false
    $xl.ScreenUpdating = $false
    $ownPid = 0
    $hwndPid = 0
    Add-Type -Namespace Win -Name NativeSess -MemberDefinition @"
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern int GetWindowThreadProcessId(System.IntPtr hWnd, out int pid);
"@ -ErrorAction SilentlyContinue
    [void][Win.NativeSess]::GetWindowThreadProcessId([System.IntPtr]$xl.Hwnd, [ref]$hwndPid)
    if ($hwndPid -gt 0) { $ownPid = $hwndPid }
    else {
        $new = @(Get-Process -Name EXCEL -ErrorAction SilentlyContinue | Where-Object { $beforeIds -notcontains $_.Id })
        if ($new.Count -gt 0) { $ownPid = $new[0].Id }
    }

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
    $p = $null
    if ($Session.Pid -gt 0) { $p = Get-Process -Id $Session.Pid -ErrorAction SilentlyContinue }
    if ($p) {
        if (-not $p.WaitForExit(10000)) { Stop-Process -Id $Session.Pid -Force -ErrorAction SilentlyContinue }
    }
}
