(tbl as table, справочник as table, optional ignoreColumns as list) as table =>
let
    _ignore = if ignoreColumns = null then {} else ignoreColumns,
    
    // Нормализация имен (убираем переносы строк, лишние пробелы)
    norm = (txt as any) as text =>
        let
            s = if txt = null then "" else Text.From(txt),
            step1 = Text.Replace(Text.Replace(Text.Replace(s, "#(lf)", " "), "#(cr)", " "), "#(tab)", " "),
            step2 = Text.Trim(step1)
        in
            step2,
    
    фактические = List.Difference(Table.ColumnNames(tbl), _ignore),
    роли = List.Distinct(Table.Column(справочник, "Роль")),
    
    // 1. Поиск: ищем, какие из фактических колонок соответствуют ролям
    маппинг = List.Transform(роли, (роль) =>
        let
            варианты = Table.Column(Table.SelectRows(справочник, each [Роль] = роль), "Вариант"),
            вариантыНорм = List.Distinct(List.Select(List.Transform(варианты, each norm(_)), each _ <> "")),
            найденный = List.First(
                List.Select(фактические, (факт) => List.Contains(вариантыНорм, norm(факт))),
                null
            )
        in
            if найденный <> null then {найденный, роль} else null
    ),
    
    валидныйМаппинг = List.RemoveNulls(маппинг),
    
    // 2. Переименовываем то, что нашли
    Переименованная = Table.RenameColumns(tbl, валидныйМаппинг),
    
    // 3. Находим, каких ролей не хватает, и добавляем их как null
    найденныеРоли = List.Transform(валидныйМаппинг, each _{1}),
    пропущенныеРоли = List.Difference(роли, найденныеРоли),
    
    СДобавленными = List.Accumulate(
        пропущенныеРоли, 
        Переименованная, 
        (state, current) => Table.AddColumn(state, current, each null, type any)
    ),
    
    // 4. Оставляем неопознанные колонки в конце, чтобы ничего не потерять
    неузнанные = List.Difference(фактические, List.Transform(валидныйМаппинг, each _{0})),
    
    // Формируем жесткий порядок колонок (игнорируемые + все роли + неизвестные)
    ИтоговыйПорядок = _ignore & роли & неузнанные
in
    Table.ReorderColumns(СДобавленными, ИтоговыйПорядок)
