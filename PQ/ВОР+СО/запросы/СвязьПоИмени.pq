let
    // Третий проход связи: строки ВОР и пункты СО, которые не связались по номеру (ни строго, ни без даты),
    // сравниваются по словам наименования. Читает ВОР_СвязьСО (связь по номеру), поэтому не зависит от Только_в_*.
    // Результат - одна строка на пару (Статус «по наименованию») или на строку ВОР (Статус «неоднозначно»).
    // «по наименованию» добавляется в связь запросом ВОР_СвязьИтог (попадает в Пересечение, Связь_ВОР_СО); лист Ошибки
    // выводит обе записи как предупреждения.
    // Слова: нижний регистр, ё->е, слова без цифр короче 3 знаков выброшены; слово без цифр сравнивается по первым 5 знакам, с цифрой - целиком.
    // Кандидат: тот же шифр и номер изменения, в наименовании СО не меньше двух слов, все слова наименования СО есть в ВОР.
    // Оценка = число слов наименования СО, бонус = слова без цифр примечания СО, найденные в ВОР,
    // затем бонус раздела (слова без цифр раздела СО, найденные в разделе ВОР; условием не является).
    // «по наименованию» - пара единственная лучшая и для строки ВОР, и для строки СО; иначе «неоднозначно».
    Колонки = {"Статус", "ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "NПП", "НаименованиеВОР",
               "ДатаСО", "NППСО", "НаименованиеСО", "КлючСО", "СтрокСО", "Номера"},
    Текст = (x as any) as text => if x = null then "" else Text.From(x),

    // --- остатки ---
    Связи = Table.Buffer(Table.SelectColumns(ВОР_СвязьСО, {"ИдСтроки", "КлючСО"})),
    КлючиСО = Table.Distinct(Table.SelectColumns(СО_Строки, {"КлючСО"})),
    НеНайдены = Table.SelectColumns(Table.NestedJoin(Связи, {"КлючСО"}, КлючиСО, {"КлючСО"}, "со", JoinKind.LeftAnti), {"ИдСтроки"}),
    БезСсылок = Table.SelectColumns(Table.NestedJoin(ВОР_Строки, {"ИдСтроки"},
        Table.Distinct(Table.SelectColumns(Связи, {"ИдСтроки"})), {"ИдСтроки"}, "п", JoinKind.LeftAnti), {"ИдСтроки"}),
    ИдыВор = Table.Distinct(Table.Combine({НеНайдены, БезСсылок})),
    ВорОст = Table.ExpandTableColumn(Table.NestedJoin(ИдыВор, {"ИдСтроки"}, ВОР_Строки, {"ИдСтроки"}, "в", JoinKind.Inner),
        "в", {"ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "Раздел", "NПП", "НаименованиеРабот"}),
    СоОст = Table.RemoveColumns(Table.NestedJoin(СО_Строки, {"КлючСО"},
        Table.Distinct(Table.SelectColumns(Связи, {"КлючСО"})), {"КлючСО"}, "в", JoinKind.LeftAnti), {"в"}),

    // --- слова ---
    Разделители = {"/", ",", "(", ")", ";", ":", "-", "–", "—", "«", "»", """", "'", "#(00A0)", "#(lf)", "#(cr)", "#(tab)", "=", "+", "*", "[", "]", "|"},
    ЕстьЦифра = (w as text) as logical => Text.Select(w, {"0".."9"}) <> "",
    Слова = (t as text) as list =>
        let
            s = List.Accumulate(Разделители, Text.Replace(Text.Lower(t), "ё", "е"), (a, d) => Text.Replace(a, d, " ")),
            w = List.Select(List.Transform(Text.Split(s, " "), each Text.Trim(_, ".")), each Text.Length(_) >= 3 or ЕстьЦифра(_)),
            основа = List.Transform(w, each if ЕстьЦифра(_) then _ else Text.Range(_, 0, List.Min({Text.Length(_), 5})))
        in List.Distinct(основа),
    // List.Buffer обязателен: без него каждый ВорЗ{i} заново вычисляет всю цепочку остатков и Excel падает.
    ВорЗ = List.Buffer(Table.ToRecords(Table.Buffer(ВорОст))),
    СоЗ = List.Buffer(Table.ToRecords(Table.Buffer(СоОст))),
    ВорСлова = List.Buffer(List.Transform(ВорЗ, each List.Buffer(Слова(Текст([НаименованиеРабот]))))),
    СоИмя = List.Buffer(List.Transform(СоЗ, each List.Buffer(Слова(Текст([НаименованиеИТехХар]))))),
    СоПрим = List.Buffer(List.Transform(СоЗ, each List.Buffer(List.Select(Слова(Текст([Примечание])), each not ЕстьЦифра(_))))),
    ВорРазд = List.Buffer(List.Transform(ВорЗ, each List.Buffer(Слова(Текст([Раздел]))))),
    СоРазд = List.Buffer(List.Transform(СоЗ, each List.Buffer(List.Select(Слова(Текст([Раздел])), each not ЕстьЦифра(_))))),
    Подходит = (i as number, j as number) as logical =>
        ВорЗ{i}[ШифрПроекта] = СоЗ{j}[ШифрПроекта] and ВорЗ{i}[НомИзмПроекта] = СоЗ{j}[НомИзмПроекта]
        and List.Count(СоИмя{j}) >= 2 and List.IsEmpty(List.Difference(СоИмя{j}, ВорСлова{i})),
    Кандидаты = List.Combine(List.Transform(List.Positions(ВорЗ), (i) =>
        List.Transform(List.Select(List.Positions(СоЗ), (j) => Подходит(i, j)),
            (j) => [и = i, ж = j, к = List.Count(СоИмя{j}) * 1000000 + List.Min({List.Count(List.Intersect({СоПрим{j}, ВорСлова{i}})), 999}) * 1000
                + List.Min({List.Count(List.Intersect({СоРазд{j}, ВорРазд{i}})), 999})]))),
    КандТаб = if List.IsEmpty(Кандидаты) then #table(type table [и = Int64.Type, ж = Int64.Type, к = Int64.Type], {})
              else Table.TransformColumnTypes(Table.FromRecords(Кандидаты), {{"и", Int64.Type}, {"ж", Int64.Type}, {"к", Int64.Type}}),
    Лучший = (т as table) as list => let м = List.Max(т[к]) in {м, List.Count(List.Select(т[к], each _ = м))},
    МаксВор = Table.AddColumn(Table.AddColumn(Table.Group(КандТаб, {"и"}, {{"р", Лучший, type list}}), "мв", each [р]{0}), "нв", each [р]{1}),
    МаксСо = Table.AddColumn(Table.AddColumn(Table.Group(КандТаб, {"ж"}, {{"р", Лучший, type list}}), "мс", each [р]{0}), "нс", each [р]{1}),
    СМаксВор = Table.ExpandTableColumn(Table.NestedJoin(КандТаб, {"и"}, Table.SelectColumns(МаксВор, {"и", "мв", "нв"}), {"и"}, "т", JoinKind.Inner), "т", {"мв", "нв"}),
    СМаксСо = Table.ExpandTableColumn(Table.NestedJoin(СМаксВор, {"ж"}, Table.SelectColumns(МаксСо, {"ж", "мс", "нс"}), {"ж"}, "т", JoinKind.Inner), "т", {"мс", "нс"}),
    СоСтатусом = Table.AddColumn(СМаксСо, "статус", each
        if [к] = [мв] and [к] = [мс] and [нв] = 1 and [нс] = 1 then "по наименованию"
        else if [к] = [мв] or [к] = [мс] then "неоднозначно" else null, type nullable text),
    ПоНаим = Table.SelectRows(СоСтатусом, each [статус] <> null),

    // Точная пара - одна запись. Неоднозначные - одна запись на строку ВОР (сводная строка ВОР «в том числе: ...»
    // совпадает по словам с десятками пунктов СО, отдельные записи на каждый только шумят).
    ТочныеЗаписи = List.Transform(Table.ToRecords(Table.SelectRows(ПоНаим, each [статус] = "по наименованию")), (p) =>
        let в = ВорЗ{p[и]}, с = СоЗ{p[ж]}
        in [Статус = "по наименованию", ИдСтроки = в[ИдСтроки],
            ШифрПроекта = в[ШифрПроекта], НомИзмПроекта = в[НомИзмПроекта], ДатаИзм = в[ДатаИзм], NПП = в[NПП],
            НаименованиеВОР = Текст(в[НаименованиеРабот]),
            ДатаСО = с[ДатаИзм], NППСО = с[NПП], НаименованиеСО = Текст(с[НаименованиеИТехХар]), КлючСО = с[КлючСО],
            СтрокСО = 1, Номера = Текст(с[NПП])]),
    НеоднГр = Table.Group(Table.SelectRows(ПоНаим, each [статус] <> "по наименованию"), {"и"}, {{"ж", each List.Sort([ж]), type list}}),
    НеоднЗаписи = List.Transform(Table.ToRecords(НеоднГр), (p) =>
        let в = ВорЗ{p[и]}, с = СоЗ{p[ж]{0}}
        in [Статус = "неоднозначно", ИдСтроки = в[ИдСтроки],
            ШифрПроекта = в[ШифрПроекта], НомИзмПроекта = в[НомИзмПроекта], ДатаИзм = в[ДатаИзм], NПП = в[NПП],
            НаименованиеВОР = Текст(в[НаименованиеРабот]),
            ДатаСО = с[ДатаИзм], NППСО = с[NПП], НаименованиеСО = Текст(с[НаименованиеИТехХар]), КлючСО = с[КлючСО],
            СтрокСО = List.Count(p[ж]),
            Номера = Text.Combine(List.Transform(List.FirstN(p[ж], 5), each Текст(СоЗ{_}[NПП])), ", ")]),
    Все = #table(Колонки, {}) & (if List.IsEmpty(ТочныеЗаписи & НеоднЗаписи) then #table(Колонки, {}) else Table.FromRecords(ТочныеЗаписи & НеоднЗаписи)),
    Итог = Table.TransformColumnTypes(Table.SelectColumns(Все, Колонки),
        {{"Статус", type text}, {"ИдСтроки", type text}, {"ДатаИзм", type date}, {"ДатаСО", type date}, {"СтрокСО", Int64.Type}})
in
    Итог
