(tbl as table) as table =>
let
    // 1. Добавляем колонку "Раздел" — берём НаименованиеРабот,
    //    если все остальные колонки в строке пустые (кроме НаименованиеРабот и Таблица)
    ДобавленРаздел = Table.AddColumn(tbl, "Раздел", each 
        let
            row = _,
            otherColumns = List.Difference(Record.FieldNames(row), {"НаименованиеРабот", "Таблица"}),
            otherValues = List.Transform(otherColumns, each Record.Field(row, _)),
            nonEmptyValues = List.Select(otherValues, each _ <> null and _ <> ""),
            isAllOthersEmpty = List.Count(nonEmptyValues) = 0
        in
            if isAllOthersEmpty 
               and row[НаименованиеРабот] <> null 
               and row[НаименованиеРабот] <> "" 
            then row[НаименованиеРабот] 
            else null
    ),
    
    // 2. Заполняем вниз
    ЗаполнениеВниз = Table.FillDown(ДобавленРаздел, {"Раздел"})
in
    ЗаполнениеВниз