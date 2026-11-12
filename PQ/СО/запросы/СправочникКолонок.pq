let
    Source = Excel.CurrentWorkbook(){[Name="СправочникКолонок"]}[Content],
    Unpivoted = Table.UnpivotOtherColumns(Source, {}, "Роль", "Вариант"),
    Filtered = Table.SelectRows(Unpivoted, each 
        [Вариант] <> null and Text.Trim(Text.From([Вариант])) <> "")
in
    Filtered
