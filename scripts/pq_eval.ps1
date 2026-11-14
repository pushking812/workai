<#
.SYNOPSIS
  Evaluates one M formula (read from a UTF-8 file) inside a COPY of a Power Query workbook
  in hidden Excel and exports the resulting table to a UTF-16 tab-separated .txt file.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\pq_eval.ps1 -Workbook data\_pq_work\book.xlsx -FormulaFile _dbg.m -OutFile data\_pq_work\dbg.txt

  The formula can use every query of the workbook (e.g. fnReadCsv, ФайлBinary).
  To see an error text, wrap the step in try and return the message as a table, because a failing
  query only gives a generic COM error (0x800A03EC).
#>
param(
    [Parameter(Mandatory = $true)][string]$Workbook,
    [Parameter(Mandatory = $true)][string]$FormulaFile,
    [Parameter(Mandatory = $true)][string]$OutFile,
    [int]$TimeoutSec = 300,
    [hashtable]$Companions, # name in the temp folder -> source path: books the workbook reads
    [switch]$AllowRunning   # by default the script refuses to run while a user's Excel is open
)

$ErrorActionPreference = "Stop"

$src = (Resolve-Path -LiteralPath $Workbook).Path
$formula = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $FormulaFile).Path, [System.Text.Encoding]::UTF8)
$outFull = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $OutFile))
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outFull) | Out-Null

$tmpDir = Join-Path $env:TEMP ("pq_eval_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$copy = Join-Path $tmpDir "book.xlsx"
Copy-Item -LiteralPath $src -Destination $copy
if ($Companions) {
    foreach ($k in $Companions.Keys) { Copy-Item -LiteralPath (Resolve-Path -LiteralPath $Companions[$k]).Path -Destination (Join-Path $tmpDir $k) }
}

. "$PSScriptRoot\excel_session.ps1"
try {
    $session = Start-ExcelSession -AllowRunning:$AllowRunning
} catch {
    Write-Output ("ERROR: " + $_.Exception.Message)
    Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}
$xl = $session.App
$xlPid = $session.Pid
$watchdog = $null
if ($xlPid -gt 0) {
    $watchdog = Start-Job -ScriptBlock {
        param($p, $s)
        Start-Sleep -Seconds $s
        Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    } -ArgumentList $xlPid, $TimeoutSec
}

$code = 0
$wb = $null
try {
    $wb = $xl.Workbooks.Open($copy)
    # "Ignore privacy levels": without it a hidden Excel fails with Formula.Firewall errors.
    try { $wb.Queries.FastCombine = $true } catch { }
    $qName = "_eval_tmp"
    [void]$wb.Queries.Add($qName, $formula)

    $ws = $wb.Worksheets.Add()
    $conn = "OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=`$Workbook`$;Location=$qName;Extended Properties=`"`""
    $lo = $ws.ListObjects.Add(0, $conn, $true, 1, $ws.Range("A1"))
    $qt = $lo.QueryTable
    $qt.CommandType = 2
    $qt.CommandText = "SELECT * FROM [$qName]"
    $qt.BackgroundQuery = $false
    [void]$qt.Refresh($false)

    $rng = $lo.Range
    $nb = $xl.Workbooks.Add()
    try {
        $target = $nb.Worksheets.Item(1).Range("A1").Resize($rng.Rows.Count, $rng.Columns.Count)
        $target.NumberFormat = "@"    # text: otherwise 81.10 would become the number 81,1
        $target.Value2 = $rng.Value2
        if (Test-Path -LiteralPath $outFull) { Remove-Item -LiteralPath $outFull -Force }
        $nb.SaveAs($outFull, 42)
    } finally {
        $nb.Close($false)
    }
    Write-Output ("OK: " + ($rng.Rows.Count - 1) + " rows, " + $rng.Columns.Count + " columns -> " + $outFull)
}
catch {
    Write-Output ("ERROR: " + $_.Exception.Message)
    $code = 1
}
finally {
    if ($wb) { try { $wb.Close($false) } catch { } }
    Stop-ExcelSession $session
    if ($watchdog) { Stop-Job $watchdog -ErrorAction SilentlyContinue; Remove-Job $watchdog -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
}
exit $code
