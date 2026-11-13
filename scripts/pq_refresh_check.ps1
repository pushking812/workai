<#
.SYNOPSIS
  Opens a COPY of a Power Query workbook in hidden Excel, refreshes every
  query-backed table and exports each one to a UTF-16 tab-separated .txt file.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\pq_refresh_check.ps1 -Workbook data\queries\book.xlsx -OutDir data\exports\_pq_check

  Result per table: <OutDir>\<table>.txt (UTF-16 LE, tab separated, header row first)
  and <OutDir>\_refresh_log.txt with errors. Exit code 0 = all tables refreshed, 1 = errors.
  The original workbook is never changed: Excel works on a copy in %TEMP%.
  The workbook must not need interactive prompts (privacy levels, file access);
  a watchdog kills Excel after -TimeoutSec.
#>
param(
    [Parameter(Mandatory = $true)][string]$Workbook,
    [string]$OutDir = "data\exports\_pq_check",
    [int]$TimeoutSec = 600,
    [switch]$AllowRunning   # by default the script refuses to run while a user's Excel is open
)

$ErrorActionPreference = "Stop"

$src = (Resolve-Path -LiteralPath $Workbook).Path
$outFull = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $OutDir))
New-Item -ItemType Directory -Force -Path $outFull | Out-Null

$tmpDir = Join-Path $env:TEMP ("pq_check_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$copy = Join-Path $tmpDir "book.xlsx"
Copy-Item -LiteralPath $src -Destination $copy

$logPath = Join-Path $outFull "_refresh_log.txt"
$log = New-Object System.Collections.Generic.List[string]
$failed = $false

. "$PSScriptRoot\excel_session.ps1"
try {
    $session = Start-ExcelSession -AllowRunning:$AllowRunning
} catch {
    Write-Output ("ERROR: " + $_.Exception.Message)
    Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}
$xl = $session.App
$xl.AskToUpdateLinks = $false
$xlPid = $session.Pid
$watchdog = $null
if ($xlPid -gt 0) {
    $watchdog = Start-Job -ScriptBlock {
        param($p, $s)
        Start-Sleep -Seconds $s
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    } -ArgumentList $xlPid, $TimeoutSec
}

$wb = $null
try {
    # Prepare the copy like a book saved by a user: "ignore privacy levels" on, and the Power Query
    # permissions re-signed by Excel itself. A book written by pq_sync import has an empty permission
    # binding, then a hidden Excel enforces privacy levels and fails with Formula.Firewall errors.
    $wb = $xl.Workbooks.Open($copy)
    try {
        $wb.Queries.FastCombine = $true
        foreach ($q in $wb.Queries) { $f = $q.Formula; $q.Formula = $f }   # marks the mashup as changed
        $wb.Save()
    } catch { $log.Add("WARN: could not prepare privacy settings: " + $_.Exception.Message) }
    $wb.Close($false)
    $wb = $xl.Workbooks.Open($copy)
    try { $wb.Queries.FastCombine = $true } catch { }

    # Queries must finish before the next step.
    foreach ($c in $wb.Connections) {
        try { $c.OLEDBConnection.BackgroundQuery = $false } catch { }
    }

    $log.Add("Source: $src")
    $log.Add("Queries in workbook: " + $wb.Queries.Count)

    # The biggest query-backed table is the final query: refresh it last.
    $big = $null
    $bigRows = 0
    foreach ($ws in $wb.Worksheets) {
        foreach ($lo in $ws.ListObjects) {
            $qt = $null
            try { $qt = $lo.QueryTable } catch { }
            if ($null -eq $qt) { continue }
            if ($lo.ListRows.Count -gt $bigRows) { $big = $lo; $bigRows = $lo.ListRows.Count }
        }
    }
    $bigName = ""
    if ($big) { $bigName = $big.Name }

    # Refresh table by table (small ones first, the final query last): RefreshAll in a hidden
    # Excel reports no errors and was seen to leave the big table without a real refresh.
    $queue = @()
    $failedTables = @{}
    foreach ($ws in $wb.Worksheets) {
        foreach ($lo in $ws.ListObjects) {
            $qt = $null
            try { $qt = $lo.QueryTable } catch { }
            if ($null -eq $qt) { continue }
            $queue += [pscustomobject]@{ Table = $lo; Rows = $lo.ListRows.Count; Name = $lo.Name }
        }
    }
    foreach ($item in ($queue | Sort-Object { if ($_.Name -eq $bigName) { 1 } else { 0 } }, Rows)) {
        $t0 = Get-Date
        try {
            $item.Table.QueryTable.BackgroundQuery = $false
            [void]$item.Table.QueryTable.Refresh($false)
            $xl.CalculateUntilAsyncQueriesDone()
            $log.Add("refreshed '" + $item.Name + "' in " + [math]::Round(((Get-Date) - $t0).TotalSeconds, 1) + " s")
        } catch {
            $failed = $true
            $failedTables[$item.Name] = $true
            $log.Add("ERROR refreshing '" + $item.Name + "': " + $_.Exception.Message)
        }
    }

    $n = 0
    foreach ($ws in $wb.Worksheets) {
        foreach ($lo in $ws.ListObjects) {
            $qt = $null
            try { $qt = $lo.QueryTable } catch { }
            if ($null -eq $qt) { continue }
            $n++
            $name = $lo.Name

            $rows = 0
            if ($lo.DataBodyRange -and $xl.WorksheetFunction.CountA($lo.DataBodyRange) -gt 0) { $rows = $lo.DataBodyRange.Rows.Count }
            if ($failedTables.ContainsKey($name)) {
                # A failed refresh rolls the table back to its old data: do not export it as fresh.
                $log.Add("SKIPPED export of '$name': refresh failed, old data not exported")
                continue
            }
            if ($rows -eq 0) {
                $failed = $true
                $log.Add("ERROR table '$name': empty after refresh")
                continue
            }
            $log.Add("OK table '$name': $rows rows")

            # Export values to a new workbook as UTF-16 tab-separated text.
            $nb = $xl.Workbooks.Add()
            try {
                $rng = $lo.Range
                $target = $nb.Worksheets.Item(1).Range("A1").Resize($rng.Rows.Count, $rng.Columns.Count)
                $target.NumberFormat = "@"    # text: otherwise 81.10 would become the number 81,1
                $target.Value2 = $rng.Value2
                $file = Join-Path $outFull ($name + ".txt")
                if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
                $nb.SaveAs($file, 42)   # xlUnicodeText
            } finally {
                $nb.Close($false)
            }
        }
    }
    # Refreshed workbook (values + queries) for further checks, e.g. scripts\check_volumes.py
    try {
        $refreshed = Join-Path $outFull "refreshed.xlsx"
        if (Test-Path -LiteralPath $refreshed) { Remove-Item -LiteralPath $refreshed -Force }
        $wb.SaveCopyAs($refreshed)
        $log.Add("Saved: $refreshed")
    } catch {
        $log.Add("WARN: could not save refreshed workbook: " + $_.Exception.Message)
    }
    if ($n -eq 0) {
        $failed = $true
        $log.Add("ERROR: no query-backed tables found in the workbook")
    }
}
catch {
    $failed = $true
    $log.Add("ERROR: " + $_.Exception.Message)
}
finally {
    if ($wb) { try { $wb.Close($false) } catch { } }
    Stop-ExcelSession $session
    if ($watchdog) { Stop-Job $watchdog -ErrorAction SilentlyContinue; Remove-Job $watchdog -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
}

$log | Set-Content -LiteralPath $logPath -Encoding UTF8
$log | ForEach-Object { Write-Output $_ }
if ($failed) { exit 1 } else { exit 0 }
