let
    Source = СписокФайлов,

    // Этап по файлу: fnReadCsv (чтение CSV, заголовок, нумерация граф, канонические колонки).
    // Ошибка файла превращается в строку с текстом в "Предупреждение".
    Таблицы = List.Transform(Table.ToRecords(Source), each
        let
            путь = Text.From(_[ПолныйПуть]),
            имя = if Record.HasFields(_, "ИмяФайла") then _[ИмяФайла] else null,
            csv = List.Last(Text.Split(путь, "\")),
            шифр = if Record.HasFields(_, "ШифрПроекта") then _[ШифрПроекта] else null,
            измНом = if Record.HasFields(_, "НомИзмПроекта") then _[НомИзмПроекта] else null,
            измДата = if Record.HasFields(_, "ДатаИзм") and _[ДатаИзм] <> null then Date.From(_[ДатаИзм]) else null,
            r = try fnReadCsv(путь, имя),
            // Ключ строки: имя CSV (<хэш>_table_N.csv, уникально) + номер строки в нём
            Ключи = (т as table) as table =>
                let
                    п1 = Table.AddIndexColumn(т, "NСтроки", 1, 1),
                    п2 = Table.AddColumn(п1, "ИдСтроки", each csv & "|" & Text.From([NСтроки]), type text),
                    п3 = Table.RemoveColumns(п2, {"NСтроки"}),
                    п4 = Table.AddColumn(п3, "ШифрПроекта", each шифр, type text),
                    п5 = Table.AddColumn(п4, "НомИзмПроекта", each измНом),
                    п6 = Table.AddColumn(п5, "ДатаИзм", each измДата, type nullable date)
                in
                    п6
        in
            if r[HasError]
            then #table({"ИмяФайла", "Предупреждение"}, {{ csv, "ОШИБКА: " & Text.From(r[Error][Message]) }})
            else Ключи(r[Value])
    ),

    // Файлы с ошибкой чтения (нет колонки КолВо) в обработку не идут, добавляются в конец
    ХорошиеТаблицы = List.Select(Таблицы, each Table.HasColumns(_, "КолВо")),
    ОшибочныеТаблицы = List.Select(Таблицы, each not Table.HasColumns(_, "КолВо")),

    Объединено = Table.Combine(ХорошиеТаблицы),

    // Запрос ВОР_База: общая таблица без разбора шифров РД/СО.
    // Из неё строятся ФайлBinary и ВОР_СвязьРД.
    // Шаги ниже работают над общей таблицей. Группировка Local по {ИмяФайла, Таблица}
    // не даёт значениям перетекать из одного файла/таблицы в другой.

    // Исходный текст "КолВо" нужен для пометки в Проверка, если он не число (166/8,3; 2х8; 17,6 6,1 11,5)
    СИсходнымКолВо = Table.AddColumn(Объединено, "КолВоИсх", each if [КолВо] = null then null else Text.Trim(Text.From([КолВо])), type nullable text),

    // Несколько значений в одной ячейке (17,6 6,1 11,5 при ЕдИзм "м3 м3 м3"; 166/8,3 при "м2/ м3"):
    // в КолВо и ЕдИзм остаётся первое значение (итог), остальные (значение и ед.изм через пробел)
    // идут в "ДопКолВО" через " | ": "6,1 м3 | 11,5 м3".
    //  - первое = сумме остальных (пробел): пометки в Проверка нет;
    //  - иначе (в т.ч. через "/"): пометка в Проверка, решает пользователь.
    // Делим, только если число значений равно числу единиц и все значения - числа.
    // "1 775" (разряды) и "2х8" не трогаем.
    числоТекст = (p as text) as logical => p <> "" and Text.Remove(p, {"0".."9", ",", "."}) = "" and Text.Remove(p, {",", "."}) <> "",
    разбить = (х as nullable text, слэш as logical) as list =>
        if х = null then {} else
            List.Select(List.Transform(Text.Split(Text.Replace(х, "#(00A0)", " "), if слэш then "/" else " "), each Text.Trim(_)), each _ <> ""),
    разобрать = (кол as nullable text, ед as nullable text) as record =>
        let
            исх = [кол = кол, ед = ед, прим = null, пом = null],
            s = if кол = null then "" else Text.Trim(Text.Replace(кол, "#(00A0)", " ")),
            слэш = Text.Contains(s, "/"),
            ч = разбить(s, слэш),
            е = разбить(ед, слэш),
            тысячи = not слэш and List.Count(ч) > 1 and List.Count(е) <> List.Count(ч)
                and List.AllTrue(List.Transform(List.Skip(ч), each Text.Length(_) = 3 and Text.Remove(_, {"0".."9"}) = "")),
            делить = кол <> null and List.Count(ч) > 1 and List.Count(ч) = List.Count(е)
                and List.AllTrue(List.Transform(ч, each числоТекст(_))) and not тысячи,
            числа = if делить then List.Transform(ч, each Number.From(Text.Replace(_, ",", "."), "en-US")) else {},
            вСумме = делить and not слэш and Number.Abs(числа{0} - List.Sum(List.Skip(числа))) < 0.051,
            доп = Text.Combine(List.Transform(List.Positions(List.Skip(ч)), each ч{_ + 1} & " " & е{_ + 1}), " | "),
            // Произведение "32х8" (число х число): КолВо = результат, ДопКолВО = первый множитель в шт.
            // ("32 шт."). Знак: х (кир./лат.), X, ×, *. Три множителя и "/" не трогаем.
            ч2 = Text.Split(Text.Replace(Text.Replace(Text.Replace(Text.Replace(Text.Replace(Text.Replace(s, "x", "х"), "X", "х"), "Х", "х"), "×", "х"), "*", "х"), " ", ""), "х"),
            умножить = кол <> null and not слэш and List.Count(ч2) = 2 and числоТекст(ч2{0}) and числоТекст(ч2{1}),
            произведение = if умножить
                then Number.Round(Number.From(Text.Replace(ч2{0}, ",", "."), "en-US") * Number.From(Text.Replace(ч2{1}, ",", "."), "en-US"), 6)
                else null
        in
            if умножить then [кол = Text.From(произведение, "en-US"), ед = ед, прим = ч2{0} & " шт.", пом = null]
            else if not делить then исх
            else [кол = ч{0}, ед = е{0},
                  прим = доп,
                  пом = if вСумме then null else "КолВо из нескольких значений «" & s & "»: взято первое, остальные в ДопКолВО"],
    Разобрано = Table.AddColumn(СИсходнымКолВо, "_р", each разобрать([КолВоИсх], if [ЕдИзм] = null then null else Text.From([ЕдИзм]))),
    СДопКолВО = Table.AddColumn(Разобрано, "ДопКолВО", each [_р][прим], type nullable text),
    СПометкойКолВо = Table.AddColumn(СДопКолВО, "ПометкаКолВо", each [_р][пом], type nullable text),
    СКолВоН = Table.AddColumn(СПометкойКолВо, "КолВо_н", each [_р][кол], type nullable text),
    СЕдН = Table.AddColumn(СКолВоН, "ЕдИзм_н", each [_р][ед], type nullable text),
    РазобраноКолВо = Table.RenameColumns(Table.RemoveColumns(СЕдН, {"КолВо", "ЕдИзм", "_р"}), {{"КолВо_н", "КолВо"}, {"ЕдИзм_н", "ЕдИзм"}}),

    // Безопасно приводим "КолВо" к числу (запятая -> точка, en-US)
    БезопасноеКолВо = Table.TransformColumns(РазобраноКолВо, {
        {"КолВо", each
            let
                s = Text.Replace(Text.Replace(Text.Replace(Text.Trim(Text.From(_)), ",", "."), " ", ""), "#(00A0)", ""),
                num = try Number.From(s, "en-US") otherwise null
            in num, type number}
    }),

    ИзмененияТипа = Table.TransformColumnTypes(БезопасноеКолВо, {
        {"Таблица", Int64.Type},
        {"NПП", type text},
        {"NВЛСР", type text},
        {"НаименованиеРабот", type text},
        {"ЕдИзм", type text},
        {"СсылкаНаЧерСпе", type text},
        {"ФормулаРасРасОбъРабИРасМат", type text}
    }),

    // Номер пункта без завершающей точки: "12." -> "12" (ключ связи с СО строится по нормализованному номеру)
    НомераНормализованы = Table.TransformColumns(ИзмененияТипа, {{"NПП", each if _ = null then null else Text.TrimEnd(Text.Trim(_), "."), type text}}),

    // Разделы (многоуровневые). Заголовок = строка, где заполнено только НаименованиеРабот
    // (NПП и все остальные колонки пусты). Номеров у заголовков в ВОР нет, поэтому уровни
    // определяются порядком строк:
    //  - подряд идущие заголовки (без данных между ними) образуют путь: верхний | ... | нижний;
    //  - новая группа из m заголовков заменяет последние m уровней действующего пути
    //    (одиночный заголовок - соседний раздел того же уровня);
    //  - заголовок ЗАГЛАВНЫМИ буквами (МОНТАЖНЫЕ РАБОТЫ) начинает путь заново.
    // Строка с номером, но без данных ("20 Монтаж сборки" с подчинёнными 20.1) остаётся
    // строкой данных (это пункт с составом, а не раздел). Если подчинённых нет - пометка в Проверка.
    РазметитьРазделы = (т as table) as table =>
        let
            пусто = (v as any) as logical => v = null or Text.Trim(Text.From(v)) = "",
            служебные = {"НаименованиеРабот", "NПП", "Таблица", "ИмяФайла", "ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм"},
            поля = Table.ColumnNames(т),
            прочие = List.Difference(поля, служебные),
            строки = Table.ToRecords(т),
            // Колонка пуста либо повторяет наименование: заголовок, растянутый по всем колонкам таблицы
            // (объединённая ячейка), попадает в CSV во все колонки
            прочиеПусты = (r as record) as logical => List.AllTrue(List.Transform(прочие, each
                let v = Record.Field(r, _)
                in пусто(v) or Text.Trim(Text.From(v)) = Text.Trim(Text.From(r[НаименованиеРабот])))),
            // NПП должен быть номером вида 12, 12., 12.3 (без пробелов и букв)
            номерПлохой = (r as record) as logical =>
                not пусто(r[NПП]) and Text.Remove(Text.Trim(Text.From(r[NПП])), {"0".."9", "."}) <> "",
            колВоПлохое = (r as record) as logical =>
                not пусто(r[КолВоИсх]) and r[КолВо] = null,
            этоЗаголовок = (r as record) as logical => not пусто(r[НаименованиеРабот]) and пусто(r[NПП]) and прочиеПусты(r),
            номерБезДанных = (r as record) as logical => not пусто(r[НаименованиеРабот]) and not пусто(r[NПП]) and прочиеПусты(r),
            заглавный = (s as text) as logical => Text.Upper(s) = s and Text.Lower(s) <> s,
            применить = (путь as list, пачка as list) as list =>
                let
                    m = List.Count(пачка),
                    d = List.Count(путь)
                in
                    if d = 0 or заглавный(пачка{0}) then пачка
                    else List.FirstN(путь, List.Max({0, d - m})) & пачка,
            подчинён = (i as number) as logical =>
                let
                    номер = Text.TrimEnd(Text.Trim(Text.From(строки{i}[NПП])), "."),
                    следующий = if i + 1 < List.Count(строки) then строки{i + 1}[NПП] else null
                in
                    not пусто(следующий) and Text.StartsWith(Text.Trim(Text.From(следующий)), номер & "."),
            старт = [путь = {}, пачка = {}, итог = {}],
            шаг = (с as record, i as number) as record =>
                let
                    r = строки{i}
                in
                    if этоЗаголовок(r)
                    then [путь = с[путь], пачка = с[пачка] & {Text.Trim(Text.From(r[НаименованиеРабот]))},
                          итог = с[итог] & {[Раздел = null, Проверка = null, Удалить = true]}]
                    else
                        let
                            путь2 = if List.IsEmpty(с[пачка]) then с[путь] else применить(с[путь], с[пачка]),
                            пометки = List.RemoveNulls({
                                if номерБезДанных(r) and not подчинён(i)
                                    then "номер без данных и без подчинённых: возможно, заголовок раздела" else null,
                                if номерПлохой(r) then "NПП не номер: " & Text.Trim(Text.From(r[NПП])) else null,
                                if колВоПлохое(r) then "КолВо не число: " & r[КолВоИсх] else null,
                                if not пусто(r[ПометкаКолВо]) then r[ПометкаКолВо] else null}),
                            пометка = if List.IsEmpty(пометки) then null else Text.Combine(пометки, "; ")
                        in
                            [путь = путь2, пачка = {},
                             итог = с[итог] & {[Раздел = if List.IsEmpty(путь2) then null else Text.Combine(путь2, " | "), Проверка = пометка, Удалить = false]}],
            разметка = List.Accumulate(List.Positions(строки), старт, шаг)[итог],
            сИндексом = Table.AddIndexColumn(т, "_i", 0, 1),
            // Строка: номер строки в таблице файла (порядок документа), считается до удаления заголовков разделов
            сСтрокой = Table.AddColumn(сИндексом, "Строка", each [_i] + 1, Int64.Type),
            сРазделом = Table.AddColumn(сСтрокой, "Раздел", each разметка{[_i]}[Раздел], type nullable text),
            сПроверкой = Table.AddColumn(сРазделом, "Проверка", each разметка{[_i]}[Проверка], type nullable text),
            сУдалить = Table.AddColumn(сПроверкой, "Удалить_строку", each разметка{[_i]}[Удалить], type logical)
        in
            Table.RemoveColumns(сУдалить, {"_i"}),
    РазделыРазмечены = Table.Combine(Table.Group(НомераНормализованы, {"ИмяФайла", "Таблица"},
        {{"Данные", each РазметитьРазделы(_), type table}}, GroupKind.Local)[Данные]),
    УдаленыСтрокиРазделов = Table.SelectRows(РазделыРазмечены, each [Удалить_строку] = false),
    УдаленыСлужебные = Table.RemoveColumns(УдаленыСтрокиРазделов, {"Удалить_строку", "КолВоИсх", "ПометкаКолВо"}),

    // Ссылки на чертежи и спецификации
    ДобавленыСсылкиРазделенные = Table.AddColumn(УдаленыСлужебные, "СсылкиРазделенные", each fnSplitReferences([СсылкаНаЧерСпе], Prefix)),
    РазвернутыСсылки = Table.ExpandRecordColumn(ДобавленыСсылкиРазделенные, "СсылкиРазделенные", {"Чертежи", "Спецификации"}, {"Чертежи", "Спецификации"}),
    // Столбцы "Чертежи" и "Спецификации" остаются: из них ФайлBinary и связующие запросы берут шифры и листы
    // Файлы с ошибкой чтения: строки с текстом в "Предупреждение" в конце
    Объединено2 = Table.Combine({РазвернутыСсылки} & ОшибочныеТаблицы),
    // Последний шаг: исходный "СсылкаНаЧерСпе" уже разобран, из итогового вывода убираем его
    Итог = Table.RemoveColumns(Объединено2, {"СсылкаНаЧерСпе"}, MissingField.Ignore)
in
    // Нет ни одного прочитанного файла (список пуст): шаги выше не вычисляются, возвращаются только строки с ошибками
    if List.IsEmpty(ХорошиеТаблицы)
    then Table.Combine({#table({"ИмяФайла"}, {})} & ОшибочныеТаблицы)
    else Итог
