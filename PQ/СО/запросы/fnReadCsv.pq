(filePath as text, optional имяФайла as nullable text) =>
let
    // Имя исходного документа: из списка (СписокСО[ИмяФайла]); если не задано - имя CSV
    ИмяДляВывода = if имяФайла = null or имяФайла = "" then List.Last(Text.Split(filePath, "\")) else имяФайла,

    // Номер таблицы документа берём из имени CSV: <хэш>_table_N.csv
    НомерТаблицы =
        let
            txt = Text.BetweenDelimiters(Text.Lower(filePath), "_table_", ".csv"),
            num = try Number.From(txt) otherwise null
        in
            if num = null then 1 else num,

    // Первая строка данных вида 1;3;4;5... (нумерация граф) - не данные
    ЭтоНумерация = (r as record) as logical =>
        let
            значения = List.Select(Record.FieldValues(r), each _ <> null and Text.Trim(Text.From(_)) <> "")
        in
            not List.IsEmpty(значения) and List.AllTrue(
                List.Transform(значения, each (try Number.From(Text.Trim(Text.From(_))) otherwise null) <> null)
            ),

    Результат = try (
        let
            // CSV: разделитель ";", UTF-8 (с BOM), переносы строк внутри кавычек
            Source = Csv.Document(File.Contents(filePath), [Delimiter = ";", Encoding = 65001]),
            // Пустые строки (все ячейки null или пробелы) удаляем до подъёма заголовка
            БезПустых = Table.SelectRows(Source, each List.AnyTrue(List.Transform(Record.FieldValues(_), each _ <> null and Text.Trim(Text.From(_)) <> ""))),
            Заголовки = Table.PromoteHeaders(БезПустых),
            БезНумерации = if Table.RowCount(Заголовки) > 0 and ЭтоНумерация(Заголовки{0}) then Table.Skip(Заголовки, 1) else Заголовки,
            ДобавленаТаблица = Table.AddColumn(БезНумерации, "Таблица", each НомерТаблицы, Int64.Type),
            ТаблицаПервой = Table.ReorderColumns(ДобавленаТаблица, {"Таблица"} & List.RemoveItems(Table.ColumnNames(БезНумерации), {"Таблица"})),
            Нормализованные = fnRenameToCanonical(ТаблицаПервой, СправочникКолонок, {"Таблица"}),
            ДобавленоИмяФайла = Table.AddColumn(Нормализованные, "ИмяФайла", each ИмяДляВывода, type text),
            Буфер = Table.Buffer(ДобавленоИмяФайла)
        in
            Буфер
    ),

    ОбработкаОшибки = if Результат[HasError] then
        (
            let
                errMessage = try Text.From(Результат[Error][Message]) otherwise "",
                errDetail = try Text.From(Результат[Error][Detail]) otherwise ""
            in
                #table(
                    {"ИмяФайла", "Предупреждение"},
                    {{ ИмяДляВывода, "ОШИБКА: " & errMessage & (if errDetail <> "" then " | Подробности: " & errDetail else "") }}
                )
        )
    else
        Результат[Value]
in
    ОбработкаОшибки
