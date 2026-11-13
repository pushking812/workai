let
    Source = СписокФайлов,

    // Этап по файлу: fnReadCsv (чтение CSV, заголовок, нумерация граф, канонические колонки).
    // Значения столбцов СО не преобразуются: что в CSV, то и в таблице (кроме NПП: убирается точка в конце).
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
                    п6 = Table.AddColumn(п5, "ДатаИзм", each измДата, type nullable date),
                    // Номер пункта без завершающей точки: "12." -> "12" (остальные значения не меняются)
                    п7 = if Table.HasColumns(п6, "NПП")
                        then Table.TransformColumns(п6, {{"NПП", each if _ = null then null else Text.TrimEnd(Text.Trim(Text.From(_)), "."), type text}})
                        else п6
                in
                    п7
        in
            if r[HasError]
            then #table({"ИмяФайла", "Предупреждение"}, {{ csv, "ОШИБКА: " & Text.From(r[Error][Message]) }})
            else Ключи(r[Value])
    ),

    // Файлы с ошибкой чтения (колонка "Предупреждение") добавляются в конец
    ХорошиеТаблицы = List.Select(Таблицы, each not Table.HasColumns(_, "Предупреждение")),
    ОшибочныеТаблицы = List.Select(Таблицы, each Table.HasColumns(_, "Предупреждение")),

    Объединено = Table.Combine(ХорошиеТаблицы),

    Итог = Table.Combine({Объединено} & ОшибочныеТаблицы)
in
    Итог
