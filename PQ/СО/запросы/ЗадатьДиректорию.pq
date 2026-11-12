let
    Source = Excel.CurrentWorkbook(){[Name="Параметры"]}[Content],
    Filter = Table.SelectRows(Source, each [Название] = "ЗадатьДиректорию"),
    Value = if Table.RowCount(Filter) > 0 then Number.From(Filter{0}[Значение]) else 0
in
    Value meta [IsParameterQuery=true, Type="Number", IsParameterQueryRequired=true]
