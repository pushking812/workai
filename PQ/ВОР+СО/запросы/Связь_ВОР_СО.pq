let
    // Таблица 4: связь «строка ВОР - строка СО». Плоская таблица: поля ВОР слева, поля СО (СО_...) справа.
    // Совпадение по ключу ШифрПроекта|НомИзмПроекта|ДатаИзм|NПП (ссылка 5 не захватывает 5.1).
    // Номера из NППРДСО, которых нет в СО, сюда не попадают (см. Только_в_ВОР).
    //
    // ЕДИНЫЙ АЛГОРИТМ распределения объёма СО (эталон на Python: core/so_allocation.py, правила в его docstring).
    // Группа = все строки ВОР, ссылающиеся на один КлючСО, и все строки СО с этим ключом. Идём от строки СО:
    //  1. слова наименования и примечания; слова с цифрами целиком, прочие по первым 5 знакам;
    //  2. все слова с цифрами из СО обязаны быть в наименовании ВОР (иначе строка ВОР не подходит);
    //  3. оценка = доля отличительных слов строки СО (не общих для всей группы), найденных в ВОР;
    //  4. строка ВОР, у которой для другой строки СО оценка выше, уступает ей;
    //  5. среди лучших остаются строки ВОР с той же единицей, что у СО;
    //  6. нет строки ВОР в единице СО - объём СО (для итога) получает первая (статус «единицы разные»); одна строка - весь объём;
    //     несколько (одна единица, допуск 0,5%): один раздел и каждая КолВо = СО - «операция над тем же материалом»
    //     (учтена первая, остальные доля 0, СО_Справочно = полный объём СО); один раздел и сумма КолВо = СО - деление
    //     по КолВо; ровно одна КолВо = СО - ей всё («по объёму»); иначе первой и «проверить вручную»;
    //  7. строка ВОР без доли остаётся в связи с долей 0: «нет аналога (другая единица)» или «ВОР без доли»;
    //     Сравнимо = 0 у таких строк (в сводной СО у них пусто, а не 0).
    // Объёмы на выбор пары не влияют, они определяют только режим учёта.
    //
    // Столбцы:
    //  ВОР_СтрокГруппы / СО_СтрокГруппы - сколько строк ВОР и строк СО в группе;
    //  СО_УчтеноОдинРаз - доля объёма строки СО, отданная этой строке ВОР (0..1, сумма по строке СО = 1): СО суммируется
    //    по СО_КолВо * СО_УчтеноОдинРаз без двойного счёта;
    //  ВОР_УчтеноОдинРаз - 1 у первой строки связи каждой строки ВОР, иначе 0: ВОР суммируется по КолВо * ВОР_УчтеноОдинРаз
    //    без повтора (строка ВОР может быть связана с несколькими строками СО и пунктами СО);
    //  СтатусПары: единственная, точно, нечётко, по остатку, дубль в СО, доля по КолВо, объём первой строке,
    //    числа не совпали, ВОР без доли; ОценкаПары - оценка 0..1 (пусто, если отличий в СО нет); ЭтоПара - 1, если доля > 0.
    Пары = Table.RenameColumns(Table.SelectColumns(ВОР_СвязьИтог, {"ИдСтроки", "NПП", "КлючСО"}), {{"NПП", "NППСО"}}),
    ВорПоля = {"ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ИмяФайла", "Таблица", "Строка", "Раздел", "NПП",
               "НаименованиеРабот", "ЕдИзм", "КолВо", "ДопКолВО"},
    СВор = Table.ExpandTableColumn(
        Table.NestedJoin(Пары, {"ИдСтроки"}, ВОР_Строки, {"ИдСтроки"}, "вор", JoinKind.Inner), "вор", ВорПоля),
    СоПоля = {"ИмяФайла", "Таблица", "Строка", "Раздел", "Комплект", "NПП", "НаименованиеИТехХар", "ЕдИзм", "КолВо", "Примечание"},
    СоИмена = List.Transform(СоПоля, each "СО_" & _),
    Соединено = Table.ExpandTableColumn(
        Table.NestedJoin(СВор, {"КлючСО"}, СО_Строки, {"КлючСО"}, "со", JoinKind.Inner), "со", СоПоля, СоИмена),
    Порядок = Table.ReorderColumns(Соединено,
        {"ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "ИмяФайла", "Таблица", "Строка", "Раздел", "NПП",
         "НаименованиеРабот", "ЕдИзм", "КолВо", "ДопКолВО", "NППСО", "КлючСО"} & СоИмена),
    Сорт = Table.Buffer(Table.Sort(Порядок, {{"ИмяФайла", Order.Ascending}, {"Таблица", Order.Ascending},
                                {"Строка", Order.Ascending}, {"СО_ИмяФайла", Order.Ascending}, {"СО_Строка", Order.Ascending}})),

    // --- слова ---
    Текст = (x as any) as text => if x = null then "" else Text.From(x),
    Разделители = {"/", ",", "(", ")", ";", ":", "-", "–", "—", "«", "»", """", "'", "#(00A0)", "#(lf)", "#(cr)", "#(tab)", "=", "+", "*", "[", "]", "|", "#(0023)"},
    // «х» (кириллица) между цифрами - это «x» (25х20х2000)
    Нормализовать = (t as text) as text =>
        let
            c = Text.ToList(Text.Replace(Text.Lower(t), "ё", "е")),
            n = List.Count(c),
            цифра = (k as number) as logical => k >= 0 and k < n and Text.PositionOf("0123456789", c{k}) >= 0,
            п = List.Transform(List.Positions(c), (k) => if (c{k} = "х" or c{k} = "×") and цифра(k - 1) and цифра(k + 1) then "x" else c{k})
        in List.Accumulate(Разделители, Text.Combine(п), (a, d) => Text.Replace(a, d, " ")),
    ЕстьЦифра = (w as text) as logical => Text.Select(w, {"0".."9"}) <> "",
    Короткое = (w as text) as text =>
        let x = Text.Range(w, 0, List.Min({5, Text.Length(w)})) in if x = "надзе" then "назем" else x,
    Слова = (t as text) as list =>
        let
            w = List.Transform(Text.Split(Нормализовать(t), " "), each Text.Trim(_, ".")),
            ok = List.Select(w, each _ <> "" and (ЕстьЦифра(_) or Text.Length(_) >= 3))
        in List.Distinct(List.Transform(ok, each if ЕстьЦифра(_) then _ else Короткое(_))),
    Ед = (x as any) as text => Text.Lower(Text.Trim(Text.Replace(Текст(x), ".", ""))),
    // «примерно равно»: допуск 0,5% (анализ по РД/: расхождений между 0 и 7,5% нет)
    Равно = (a as nullable number, b as nullable number) as logical =>
        a <> null and b <> null and b <> 0 and Number.Abs(a - b) / Number.Abs(b) <= 0.005,
    СоКлюч = (р as record) as text => Текст(р[СО_ИмяФайла]) & "~" & Текст(р[СО_Таблица]) & "~" & Текст(р[СО_Строка]),

    // --- распределение объёма одной группы (один КлючСО) ---
    Распределить = (г as table) as table =>
        let
            строки = List.Buffer(Table.ToRecords(г)),
            скл = List.Buffer(List.Transform(строки, СоКлюч)),
            вКл = List.Buffer(List.Distinct(List.Transform(строки, each _[ИдСтроки]))),
            сКл = List.Buffer(List.Distinct(скл)),
            nv = List.Count(вКл),
            ns = List.Count(сКл),
            вЗап = List.Buffer(List.Transform(вКл, (k) => строки{List.PositionOf(List.Transform(строки, each _[ИдСтроки]), k)})),
            сЗап = List.Buffer(List.Transform(сКл, (k) => строки{List.PositionOf(скл, k)})),
            vw = List.Buffer(List.Transform(вЗап, each Слова(Текст(_[НаименованиеРабот])))),
            sw = List.Buffer(List.Transform(сЗап, each Слова(Текст(_[СО_НаименованиеИТехХар]) & " " & Текст(_[СО_Примечание])))),
            общие = List.Accumulate(sw, sw{0}, (a, s) => List.Intersect({a, s})),
            отл = List.Buffer(List.Transform(sw, each List.Difference(_, общие))),
            // числа строки СО содержатся в наименовании ВОР
            совм0 = (i as number, j as number) as logical =>
                List.IsEmpty(List.Select(sw{j}, each ЕстьЦифра(_) and not List.Contains(vw{i}, _))),
            // ни одна строка ВОР не подходит по числам: проверка для этой строки СО отключается (статус «числа не совпали»)
            нет = List.Buffer(List.Transform(List.Positions(sw), (j) =>
                not List.AnyTrue(List.Transform(List.Positions(vw), (i) => совм0(i, j))))),
            оц = (i as number, j as number) as number =>
                if not (нет{j} or совм0(i, j)) then -1
                else if List.IsEmpty(отл{j}) then 0
                else List.Count(List.Intersect({отл{j}, vw{i}})) / List.Count(отл{j}),
            sc = List.Buffer(List.Transform(List.Positions(vw), (i) =>
                List.Buffer(List.Transform(List.Positions(sw), (j) => оц(i, j))))),
            лучшая = List.Buffer(List.Transform(sc, each List.Max(_))),
            ед = List.Buffer(List.Transform(вЗап, each Ед(_[ЕдИзм]))),
            кол = List.Buffer(List.Transform(вЗап, each _[КолВо])),
            решение = (j as number) as list =>
                let
                    все = List.Select(List.Positions(vw), each sc{_}{j} >= 0),
                    вершина = List.Max(List.Transform(все, each sc{_}{j})),
                    л1 = List.Select(все, each sc{_}{j} = вершина),
                    своб = List.Select(л1, each sc{_}{j} >= лучшая{_}),
                    л2 = if List.IsEmpty(своб) then л1 else своб,
                    ту = List.Select(л2, each ед{_} = Ед(сЗап{j}[СО_ЕдИзм])),
                    ско = сЗап{j}[СО_КолВо],
                    ко = List.Transform(ту, each кол{_}),
                    есть = ско <> null and ско > 0 and List.AllTrue(List.Transform(ко, each _ <> null and _ > 0)),
                    одинРаздел = List.Count(List.Distinct(List.Transform(ту, each Текст(вЗап{_}[Раздел])))) = 1,
                    рав = List.Transform(ко, each Равно(_, ско))
                in
                    // нет строки ВОР в единице СО: объём СО (для итога) получает первая, сравнивать объёмы нельзя
                    if List.IsEmpty(ту) then {[в = л2{0}, с = j, д = 1, вид = "единицы"]}
                    else if List.Count(ту) = 1 then {[в = ту{0}, с = j, д = 1, вид = "один"]}
                    // операции над одним материалом: каждая КолВо = СО, один раздел; учтена первая, остальные справочно
                    else if есть and одинРаздел and List.AllTrue(рав) then
                        {[в = ту{0}, с = j, д = 1, вид = "операция"]} &
                        List.Transform(List.Skip(ту, 1), (k) => [в = k, с = j, д = 0, вид = "операция"])
                    // деление: сумма КолВо = СО, один раздел
                    else if есть and одинРаздел and Равно(List.Sum(ко), ско) then
                        List.Transform(ту, (k) => [в = k, с = j, д = кол{k} / List.Sum(ко), вид = "доля"])
                    // ровно одна строка равна СО
                    else if есть and List.Count(List.Select(рав, each _)) = 1 then
                        {[в = ту{List.PositionOf(рав, true)}, с = j, д = 1, вид = "объём"]}
                    else {[в = ту{0}, с = j, д = 1, вид = "вручную"]},
            доли = List.Buffer(List.Combine(List.Transform(List.Positions(sw), решение))),
            получили = List.Buffer(List.Distinct(List.Transform(доли, each [в]))),
            без = List.Transform(List.Select(List.Positions(vw), each not List.Contains(получили, _)),
                (k) => [в = k, с = List.PositionOf(sc{k}, List.Max(sc{k})), д = 0, вид = "без"]),
            всё = доли & без,
            статус = (р as record) as text =>
                if р[вид] = "операция" then "операция над тем же материалом"
                else if р[вид] = "без" and ед{р[в]} <> Ед(сЗап{р[с]}[СО_ЕдИзм]) then "нет аналога (другая единица)"
                else if р[д] = 0 then "ВОР без доли"
                else if ns = 1 and (nv = 1 or р[вид] = "один") then "единственная"
                else if ns > 1 and List.IsEmpty(отл{р[с]}) then "дубль в СО"
                else if р[вид] = "доля" then "доля по КолВо"
                else if р[вид] = "единицы" then "единицы разные"
                else if р[вид] = "объём" then "по объёму"
                else if р[вид] = "вручную" then "проверить вручную"
                else if sc{р[в]}{р[с]} >= 1 then "точно"
                // проверка чисел отключена, и пара не точная по словам: проверьте вручную
                else if нет{р[с]} then "числа не совпали"
                else if sc{р[в]}{р[с]} > 0 then "нечётко"
                else "по остатку",
            запись = (р as record) as record =>
                Record.Combine({
                    строки{List.First(List.Select(List.Positions(строки), each строки{_}[ИдСтроки] = вКл{р[в]} and скл{_} = сКл{р[с]}))},
                    [ВОР_СтрокГруппы = nv, СО_СтрокГруппы = ns, СО_УчтеноОдинРаз = р[д],
                     СтатусПары = статус(р),
                     ОценкаПары = if List.IsEmpty(отл{р[с]}) or sc{р[в]}{р[с]} < 0 then null else sc{р[в]}{р[с]},
                     ЭтоПара = if р[д] > 0 then 1 else 0,
                     СО_Справочно = if р[вид] = "операция" then сЗап{р[с]}[СО_КолВо] else null,
                     Сравнимо = if р[вид] = "без" then 0 else 1]})
        in Table.FromRecords(List.Transform(всё, запись)),

    НовыеСтолбцы = {"ВОР_СтрокГруппы", "СО_СтрокГруппы", "СО_УчтеноОдинРаз", "СтатусПары", "ОценкаПары", "ЭтоПара", "СО_Справочно", "Сравнимо"},
    ПоГруппам = Table.Group(Сорт, {"КлючСО"}, {{"т", Распределить, type table}}),
    // пустая заготовка со столбцами нужна, когда строк нет (пустые книги ВОР и СО): иначе Combine даёт таблицу без столбцов
    Спаренные = Table.Combine(ПоГруппам[т] & {#table(Table.ColumnNames(Сорт) & НовыеСтолбцы, {})}),
    Отсортировано = Table.Sort(Спаренные, {{"ИмяФайла", Order.Ascending}, {"Таблица", Order.Ascending},
                                           {"Строка", Order.Ascending}, {"СО_ИмяФайла", Order.Ascending}, {"СО_Строка", Order.Ascending}}),
    // ВОР_УчтеноОдинРаз: 1 у первой строки связи каждой строки ВОР
    Инд = Table.AddIndexColumn(Table.Buffer(Отсортировано), "_н", 0, 1),
    ПервыеВор = Table.Group(Инд, {"ИдСтроки"}, {{"_мин", each List.Min([_н]), Int64.Type}}),
    СПервой = Table.ExpandTableColumn(Table.NestedJoin(Инд, {"ИдСтроки"}, ПервыеВор, {"ИдСтроки"}, "п", JoinKind.LeftOuter), "п", {"_мин"}),
    ВорОдинРаз = Table.RemoveColumns(
        Table.AddColumn(СПервой, "ВОР_УчтеноОдинРаз", each if [_н] = [_мин] then 1 else 0, Int64.Type), {"_н", "_мин"}),
    Упорядочено = Table.ReorderColumns(ВорОдинРаз,
        List.Transform(Table.ColumnNames(Сорт) & {"ВОР_СтрокГруппы", "СО_СтрокГруппы", "СО_УчтеноОдинРаз", "ВОР_УчтеноОдинРаз",
                                                  "СтатусПары", "ОценкаПары", "ЭтоПара", "СО_Справочно", "Сравнимо"}, each _)),
    // ExpandTableColumn теряет типы развёрнутых столбцов - задаём явно (иначе в Excel дата станет числом)
    Итог = Table.TransformColumnTypes(Упорядочено, {{"ДатаИзм", type date}, {"КолВо", type number}, {"СО_КолВо", type number},
        {"СтатусПары", type text}, {"ОценкаПары", type number}, {"ЭтоПара", Int64.Type},
        {"ВОР_СтрокГруппы", Int64.Type}, {"СО_СтрокГруппы", Int64.Type}, {"СО_УчтеноОдинРаз", type number},
        {"ВОР_УчтеноОдинРаз", Int64.Type}, {"СО_Справочно", type number}, {"Сравнимо", Int64.Type}})
in
    Итог
