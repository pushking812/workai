let
    Source = Excel.CurrentWorkbook(){[Name="Параметры"]}[Content],
    Filter = Table.SelectRows(Source, each [Название] = "РабочаяДиректория"),
    Value = if Table.RowCount(Filter) > 0 then Text.From(Filter{0}[Значение]) else "."
in
    Value meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]
