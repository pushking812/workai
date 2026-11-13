param(
    [Parameter(Mandatory)][string]$Workbook,
    [Parameter(Mandatory)][string]$Out,
    [string]$Table = "Связь_ВОР_СО",
    [string]$SheetName = "Сводная",
    [switch]$AllowRunning
)
# Adds a PivotTable over the query table $Table (one VOR item -> its SO rows) and saves to $Out.
. "$PSScriptRoot\excel_session.ps1"
$ErrorActionPreference = "Stop"
$src = (Resolve-Path $Workbook).Path
$dst = [System.IO.Path]::GetFullPath($Out)
$s = Start-ExcelSession -AllowRunning:$AllowRunning
try {
    $xl = $s.App
    $wb = $xl.Workbooks.Open($src)
    $lo = $null
    foreach ($ws in $wb.Worksheets) { foreach ($l in $ws.ListObjects) { if ($l.Name -eq $Table) { $lo = $l } } }
    if (-not $lo) { throw "table $Table not found" }
    foreach ($ws in @($wb.Worksheets)) { if ($ws.Name -eq $SheetName) { $ws.Delete() } }
    $sh = $wb.Worksheets.Add()
    $sh.Name = $SheetName
    $pc = $wb.PivotCaches().Create(1, $Table)          # xlDatabase, source = table name
    $pt = $pc.CreatePivotTable($sh.Range("A3"), "СводнаяСвязь")
    $pt.ManualUpdate = $true
    $pt.RowAxisLayout(1)                               # tabular
    $pt.NullString = ""
    $pt.HasAutoFormat = $false
    $pf = $pt.PivotFields("ШифрПроекта"); $pf.Orientation = 3; $pf.Position = 1   # page filter
    $rows = "NПП", "НаименованиеРабот", "ЕдИзм", "КолВо", "СО_NПП", "СО_НаименованиеИТехХар", "СО_ЕдИзм"
    $i = 1
    foreach ($n in $rows) {
        $f = $pt.PivotFields($n); $f.Orientation = 1; $f.Position = $i; $i++
        $f.Subtotals = @($false,$false,$false,$false,$false,$false,$false,$false,$false,$false,$false,$false)
        $f.RepeatLabels = $false
    }
    # СО_КолВо — текст, поэтому это тоже поле строк (без значений/сумм).
    $f = $pt.PivotFields("СО_КолВо"); $f.Orientation = 1; $f.Position = $i
    $f.Subtotals = @($false,$false,$false,$false,$false,$false,$false,$false,$false,$false,$false,$false)
    $f.RepeatLabels = $false
    $pt.ColumnGrand = $false; $pt.RowGrand = $false
    $pt.ManualUpdate = $false
    $pc.RefreshOnFileOpen = $true
    $wb.SaveAs($dst, 51)
    $wb.Close($false)
    "Saved: $dst"
} finally {
    Stop-ExcelSession $s
}
