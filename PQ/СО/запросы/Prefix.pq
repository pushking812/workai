let
    Source = Excel.CurrentWorkbook(){[Name="Параметры"]}[Content],
    Filter = Table.SelectRows(Source, each [Название] = "Префикс"),
    Value = if Table.RowCount(Filter) > 0 then Text.From(Filter{0}[Значение]) else error "Не задан Префикс в таблице Параметры"
in
    Value meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]
