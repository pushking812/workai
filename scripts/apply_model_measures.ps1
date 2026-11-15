# Меры модели книги ВОР+СО (СуммаСО, СуммаВОР, СправочноСО, СтатусСвязи): -Apply задаёт формулы, -Test строит временный сводный для проверки, -Save сохраняет. Excel пользователя должен быть закрыт.
param([string]$Path, [switch]$Apply, [switch]$Test, [switch]$Save)
. "$PSScriptRoot\excel_session.ps1"
$s = Start-ExcelSession
try {
    $xl = $s.App
    $wb = $xl.Workbooks.Open((Resolve-Path $Path).Path)
    $m = $wb.Model
    $TN = "'Связь_ВОР_СО'"
    $fmt = 'IF(s = TRUNC(s); FORMAT(s; "# ##0"); FORMAT(s; "# ##0.###############"))'
    $fSO = "VAR s = SUMX($TN; $TN[СО_КолВо] * $TN[СО_УчтеноОдинРаз])" + "`n" + "RETURN IF(SUM($TN[Сравнимо]) = 0; BLANK(); $fmt)"
    $fVOR = "VAR s = SUMX($TN; $TN[КолВо] * $TN[ВОР_УчтеноОдинРаз])" + "`n" + "RETURN $fmt"
    $fRef = "VAR s = SUMX(SUMMARIZE($TN; $TN[СО_ИмяФайла]; $TN[СО_Строка]; `"v`"; MAX($TN[СО_Справочно])); [v])" + "`n" + "RETURN IF(ISBLANK(MAX($TN[СО_Справочно])); BLANK(); $fmt)"
    $fSt = "CONCATENATEX(VALUES($TN[СтатусПары]); $TN[СтатусПары]; `" | `")"
    if ($Apply) {
        $have = @{}
        foreach ($ms in $m.ModelMeasures) { $have[$ms.Name] = $ms }
        $tbl = $null
        foreach ($mt in $m.ModelTables) { if ($mt.Name -eq "Связь_ВОР_СО") { $tbl = $mt } }
        $have["СуммаСО"].Formula = $fSO
        $have["СуммаВОР"].Formula = $fVOR
        if ($have.ContainsKey("СправочноСО")) { $have["СправочноСО"].Formula = $fRef }
        else { [void]$m.ModelMeasures.Add("СправочноСО", $tbl, $fRef, $m.ModelFormatGeneral, "Полный объём СО для строк со статусом 'операция над тем же материалом' (один раз на строку СО, в сумму СО не входит)") }
        if ($have.ContainsKey("СтатусСвязи")) { $have["СтатусСвязи"].Formula = $fSt }
        else { [void]$m.ModelMeasures.Add("СтатусСвязи", $tbl, $fSt, $m.ModelFormatGeneral, "Статус связи ВОР-СО (все статусы строк в ячейке)") }
        Write-Output "APPLIED"
    }
    foreach ($ms in $m.ModelMeasures) { Write-Output ("MEASURE " + $ms.Name) }
    if ($Test) {
        $pc = $wb.PivotCaches().Create(2, $wb.Connections.Item("ThisWorkbookDataModel"), 5)
        $ws = $wb.Worksheets.Add()
        $pt = $pc.CreatePivotTable($ws.Range("A3"), "_tmp")
        $pt.CubeFields.Item("[Связь_ВОР_СО].[ИдСтроки]").Orientation = 1
        $pt.CubeFields.Item("[Связь_ВОР_СО].[СО_NПП]").Orientation = 1
        foreach ($n in "СуммаВОР", "СуммаСО", "СправочноСО", "СтатусСвязи") {
            $cf = $pt.CubeFields.Item("[Measures].[$n]")
            $cf.Orientation = 4
        }
        $ur = $ws.UsedRange
        $out = @()
        foreach ($r in 1..[Math]::Min($ur.Rows.Count, 400)) {
            $line = @()
            foreach ($c in 1..6) { $line += [string]$ws.Cells.Item($r + 2, $c).Text }
            $out += ($line -join " ; ")
        }
        $out | Out-File -Encoding utf8 $env:TEMP\pivot_test.txt
        Write-Output ("TEST rows: " + $out.Count)
    }
    if ($Save) { $wb.Save() }
    $wb.Close($false)
} finally { Stop-ExcelSession $s }

