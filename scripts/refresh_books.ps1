<#
.SYNOPSIS
  Opens the given workbooks one after another in its own hidden Excel, refreshes all queries,
  saves each book in place and closes it. Used by the "Сформировать запросы" button (mode ВОР+СО):
  ВОР and СО first, then the book that reads them.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\refresh_books.ps1 -Books "C:\q\ВОР_1.xlsx|C:\q\СО_1.xlsx|C:\q\ВОР+СО_1.xlsx"

  Exit code: 0 all refreshed and saved, 1 errors (see output), 2 a user's Excel is already open (nothing done).
  A book whose refresh failed is NOT saved, and the following books are not refreshed.
#>
param(
    [Parameter(Mandatory = $true)][string]$Books,   # paths separated by |
    [int]$TimeoutSec = 900
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$paths = @($Books -split '\|' | Where-Object { $_ })

. "$PSScriptRoot\excel_session.ps1"
try {
    $session = Start-ExcelSession
} catch {
    Write-Output ("EXCEL_BUSY: " + $_.Exception.Message)
    exit 2
}
$xl = $session.App
$xl.AskToUpdateLinks = $false
$watchdog = $null
if ($session.Pid -gt 0) {
    $watchdog = Start-Job -ScriptBlock {
        param($p, $s)
        Start-Sleep -Seconds $s
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    } -ArgumentList $session.Pid, $TimeoutSec
}

$failed = $false
$wb = $null
try {
    foreach ($path in $paths) {
        $name = [System.IO.Path]::GetFileName($path)
        $t0 = Get-Date
        # Same preparation as in pq_refresh_check.ps1: a book made from a template has an unsigned
        # Power Query binding; re-assign the formulas so that privacy levels are ignored.
        $wb = $xl.Workbooks.Open($path)
        try {
            $wb.Queries.FastCombine = $true
            foreach ($q in $wb.Queries) { $f = $q.Formula; $q.Formula = $f }
            $wb.Save()
        } catch { Write-Output ("WARN ${name}: could not prepare privacy settings: " + $_.Exception.Message) }
        $wb.Close($false)
        $wb = $xl.Workbooks.Open($path)
        try { $wb.Queries.FastCombine = $true } catch { }
        foreach ($c in $wb.Connections) { try { $c.OLEDBConnection.BackgroundQuery = $false } catch { } }

        # Table by table, small ones first and the biggest (final) one last.
        $queue = @()
        foreach ($ws in $wb.Worksheets) {
            foreach ($lo in $ws.ListObjects) {
                $qt = $null
                try { $qt = $lo.QueryTable } catch { }
                if ($null -eq $qt) { continue }
                $queue += [pscustomobject]@{ Table = $lo; Rows = $lo.ListRows.Count; Name = $lo.Name }
            }
        }
        if ($queue.Count -eq 0) { throw "no query-backed tables in $name" }
        $bad = $false
        foreach ($item in ($queue | Sort-Object Rows)) {
            try {
                $item.Table.QueryTable.BackgroundQuery = $false
                [void]$item.Table.QueryTable.Refresh($false)
                $xl.CalculateUntilAsyncQueriesDone()
            } catch {
                $bad = $true
                Write-Output ("ERROR ${name}: refresh of '" + $item.Name + "' failed: " + $_.Exception.Message)
            }
        }
        # Data model (pivot sources) of the ВОР+СО book, if the user added one.
        if (-not $bad) {
            foreach ($c in $wb.Connections) {
                $isModel = $false
                # type 7 = the model itself; a query loaded to the model ("Запрос — Связь_ВОР_СО") has InModel = True
                try { $isModel = ($c.Type -eq 7) -or [bool]$c.InModel } catch { }
                if (-not $isModel) { continue }
                try { $c.Refresh(); $xl.CalculateUntilAsyncQueriesDone() }
                catch { Write-Output ("WARN ${name}: model connection '" + $c.Name + "': " + $_.Exception.Message) }
            }
            foreach ($pc in $wb.PivotCaches()) { try { $pc.Refresh() } catch { } }
        }
        if ($bad) {
            $failed = $true
            $wb.Close($false); $wb = $null
            Write-Output "FAILED ${name}: not saved, next books skipped"
            break
        }
        # Sheet "Ошибки" (book ВОР+СО): counts by ТипПроблемы for the app's short summary
        foreach ($ws in $wb.Worksheets) {
            foreach ($lo in $ws.ListObjects) {
                if ($lo.Name -ne "Ошибки") { continue }
                try {
                    $counts = @{}
                    if ($lo.DataBodyRange) {
                        foreach ($v in $lo.ListColumns.Item("ТипПроблемы").DataBodyRange.Value2) {
                            if ($v) { $counts[[string]$v] = 1 + [int]$counts[[string]$v] }
                        }
                    }
                    $line = ($counts.GetEnumerator() | Sort-Object Name | ForEach-Object { $_.Name + "=" + $_.Value }) -join ";"
                    Write-Output ("ISSUES ${name}: " + $line)
                } catch { Write-Output ("WARN ${name}: could not count issues: " + $_.Exception.Message) }
            }
        }
        # ДатаИзм: after a refresh Excel leaves only the first row with a date format, so set it for the whole column
        foreach ($ws in $wb.Worksheets) {
            foreach ($lo in $ws.ListObjects) {
                try {
                    $dc = $null
                    foreach ($lc in $lo.ListColumns) { if ($lc.Name -eq "ДатаИзм") { $dc = $lc; break } }
                    if ($dc -and $lo.DataBodyRange) {
                        # Russian Excel only: the local code is ДД/ММ/ГГГГ ("dd/mm/yyyy" would become literal text).
                        $first = $dc.DataBodyRange.Cells.Item(1, 1)
                        $first.NumberFormatLocal = 'ДД/ММ/ГГГГ'
                        if ($first.Text -match '^\d\d/\d\d/\d{4}$') { $dc.DataBodyRange.NumberFormatLocal = 'ДД/ММ/ГГГГ' }
                        else { Write-Output ("WARN ${name}: date format not applied for '" + $lo.Name + "'") }
                    }
                } catch { Write-Output ("WARN ${name}: date format on '" + $lo.Name + "': " + $_.Exception.Message) }
            }
        }
        $wb.Save()
        $wb.Close($false); $wb = $null
        Write-Output ("OK $name refreshed and saved in " + [math]::Round(((Get-Date) - $t0).TotalSeconds, 1) + " s")
    }
}
catch {
    $failed = $true
    Write-Output ("ERROR: " + $_.Exception.Message)
}
finally {
    if ($wb) { try { $wb.Close($false) } catch { } }
    Stop-ExcelSession $session
    if ($watchdog) { Stop-Job $watchdog -ErrorAction SilentlyContinue; Remove-Job $watchdog -Force -ErrorAction SilentlyContinue }
}
if ($failed) { exit 1 } else { exit 0 }
