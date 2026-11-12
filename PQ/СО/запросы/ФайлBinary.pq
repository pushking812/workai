let
    База = СО_База,

    // Строки файлов с ошибкой чтения (колонка "Предупреждение") отделяем и возвращаем в конец
    ЕстьОшибки = Table.HasColumns(База, "Предупреждение"),
    ОшибочныеТаблицы = if ЕстьОшибки
        then {Table.SelectColumns(Table.SelectRows(База, each [Предупреждение] <> null), {"ИмяФайла", "Предупреждение"})}
        else {},
    Хорошие = if ЕстьОшибки
        then Table.RemoveColumns(Table.SelectRows(База, each [Предупреждение] = null), {"Предупреждение"})
        else База,

    // Служебные колонки и роли шаблона идут в фиксированном порядке, роли пользователя - после них, ключ - последним
    Начало = {"ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ИмяФайла", "Таблица",
              "NПП", "НаименованиеИТехХар", "ТипМаркаОбозначение", "КодПродукции", "Поставщик",
              "ЕдИзм", "КолВо", "Масса1ЕдКг", "Примечание"},

    // Повторы номера пункта: в одном файле NПП может встречаться несколько раз с разными объёмами
    // и примечаниями. Если все остальные поля (кроме ИдСтроки, КолВо, Примечание) совпадают:
    //   1) объём каждой строки дописывается в её примечание ("примечание: объём"),
    //   2) строки сворачиваются в одну: объёмы суммируются, примечания объединяются через "; ".
    // Не сворачиваются: строки без NПП и группы, где объём не число (тогда строки остаются как есть).
    СлужебныеПоля = {"ИдСтроки", "КолВо", "Примечание"},
    Свернуть = (т as table) as table =>
        let
            строки = Table.ToRecords(т),
            пусто = (х) => х = null or Text.Trim(Text.From(х)) = "",
            нпп = строки{0}[NПП],
            объёмыТекст = List.Transform(строки, each if пусто(_[КолВо]) then null else Text.Trim(Text.From(_[КолВо]))),
            числа = List.Transform(объёмыТекст, each
                if _ = null then null
                else try Number.FromText(Text.Replace(Text.Replace(_, " ", ""), ",", "."), "en-US") otherwise null),
            можно = Table.RowCount(т) > 1 and not пусто(нпп) and not List.Contains(числа, null),
            запятая = List.AnyTrue(List.Transform(объёмыТекст, each Text.Contains(_, ","))),
            сумма = List.Sum(числа),
            суммаТекст = (if запятая then Text.Replace(Number.ToText(сумма, "0.###############", "en-US"), ".", ",")
                          else Number.ToText(сумма, "0.###############", "en-US")),
            // ед. изм. одинакова во всей группе (входит в ключи группировки)
            ед = if not Table.HasColumns(т, "ЕдИзм") or пусто(строки{0}[ЕдИзм]) then "" else " " & Text.Trim(Text.From(строки{0}[ЕдИзм])),
            заметки = List.Transform(List.Positions(строки), each
                let
                    п = if пусто(строки{_}[Примечание]) then null else Text.Trim(Text.From(строки{_}[Примечание]))
                in
                    if п = null then объёмыТекст{_} & ед else п & ": " & объёмыТекст{_} & ед),
            первая = Table.FirstN(т, 1)
        in
            if not можно then т
            else Table.TransformColumns(первая, {{"КолВо", each суммаТекст, type text},
                                                 {"Примечание", each Text.Combine(заметки, "; "), type text}}),
    Свёрнутые = if not Table.HasColumns(Хорошие, {"ИдСтроки", "NПП", "КолВо", "Примечание"}) or Table.IsEmpty(Хорошие) then Хорошие else
        let
            ключи = List.Difference(Table.ColumnNames(Хорошие), СлужебныеПоля),
            группы = Table.Group(Хорошие, ключи, {{"т", each _, type table}})
        in
            Table.Combine(List.Transform(Table.Column(группы, "т"), each Свернуть(_))),

    // Ключ связи с ВОР: ШифрПроекта | НомИзмПроекта | ДатаИзм (гггг-мм-дд) | NПП.
    // Тот же вид ключа строит запрос ВОР_СвязьСО в шаблоне ВОР.
    // Если ни один файл не прочитан, данных нет: остаются только строки с ошибками.
    Данные = if not Table.HasColumns(Хорошие, "ИдСтроки") then #table({}, {}) else
        let
            КлючСО = Table.AddColumn(Свёрнутые, "КлючСО", each
                (if [ШифрПроекта] = null then "" else [ШифрПроекта]) & "|"
                & (if [НомИзмПроекта] = null then "" else Text.From([НомИзмПроекта])) & "|"
                & (if [ДатаИзм] = null then "" else Date.ToText([ДатаИзм], "yyyy-MM-dd")) & "|"
                & (if [NПП] = null then "" else Text.Trim(Text.From([NПП]))), type text),
            Порядок = Table.ReorderColumns(КлючСО, Начало)
        in
            Table.ReorderColumns(Порядок, List.RemoveItems(Table.ColumnNames(Порядок), {"КлючСО"}) & {"КлючСО"}),

    // Файлы, которые не удалось прочитать: строка с текстом ошибки
    Итог = Table.Combine({Данные} & ОшибочныеТаблицы)
in
    Итог
