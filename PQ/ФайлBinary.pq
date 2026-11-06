// Запрос ФайлBinary
let
    Source = File.Contents(FilePath),
    
    // 1. Распаковка и парсинг документа
    Extracted = fxZipExtractAll(Source),
    DocumentXml = Extracted{[FileName="word/document.xml"]}[Content],
    XmlRecord = Xml.Document(DocumentXml),
    
    // 3. Извлечение текста с переносами
    ExtractText = (node as record) as text =>
        let
            name = node[Name],
            isText = Text.EndsWith(name, "t"),
            isBreak = Text.EndsWith(name, "br") or Text.EndsWith(name, "cr"),
            isPara = Text.EndsWith(name, "p"),
            val = if Record.HasFields(node, "Value") and node[Value] is text then node[Value] else "",
            currentText = if isText then val else if isBreak then "#(lf)" else "",
            childTable = if Record.HasFields(node, "Value") and node[Value] is table then node[Value]
                         else if Record.HasFields(node, "Table") and node[Table] is table then node[Table]
                         else null,
            childrenText = if childTable <> null then
                               Text.Combine(List.Transform(Table.ToRecords(childTable), each @ExtractText(_)), "")
                           else "",
            result = currentText & childrenText & (if isPara and not isText and childrenText <> "" then "#(lf)" else "")
        in
            result,

    // 4. Извлечение gridSpan (объединенных ячеек)
    GetGridSpan = (cell as record) as number =>
        let
            tcPr = fnFindNodes(cell, "tcPr"),
            gridSpans = if List.Count(tcPr) > 0 then fnFindNodes(tcPr{0}, "gridSpan") else {},
            spanVal = if List.Count(gridSpans) > 0 then 
                          let 
                              attrs = gridSpans{0}[Attributes],
                              val = try Record.Field(attrs, "w:val") otherwise try Record.Field(attrs, "val") otherwise "1"
                          in Number.FromText(val)
                      else 1
        in
            spanVal,

    // 5. Находим ВСЕ таблицы в документе
    AllTables = fnFindNodes(XmlRecord, "tbl"),

    // 6. Обрабатываем каждую таблицу отдельно (добавляем TableID)
    ProcessedTables = List.Transform(List.Positions(AllTables), (tblIndex) =>
        let
            currentTable = AllTables{tblIndex},
            rows = fnFindNodes(currentTable, "tr"),
            processedRows = List.Transform(rows, (row) =>
                let
                    cells = fnFindNodes(row, "tc"),
                    // Для каждой ячейки: извлекаем текст и проверяем gridSpan
                    cellData = List.Transform(cells, (cell) =>
                        let
                            txt = Text.Trim(ExtractText(cell), {" ", "#(lf)", "#(cr)"}),
                            span = GetGridSpan(cell),
                            // Добиваем пустыми значениями, если ячейка объединена
                            padded = {txt} & List.Repeat({""}, span - 1)
                        in
                            [Texts = padded]
                    ),
                    // Склеиваем ячейки с учетом gridSpan
                    flatTexts = List.Combine(List.Transform(cellData, each [Texts]))
                in
                    [TableID = tblIndex + 1, Texts = flatTexts]
            )
        in
            processedRows
    ),
    
    AllRowData = List.Combine(ProcessedTables),

    // 7. Динамическое выравнивание
    МаксКолонок = List.Max(List.Transform(AllRowData, each List.Count(_[Texts]))),
    ВыровненныеСтроки = List.Transform(AllRowData, each {_[TableID]} & _[Texts] & List.Repeat({""}, МаксКолонок - List.Count(_[Texts]))),
    ИменаКолонок = {"Таблица"} & List.Transform({1..МаксКолонок}, each "Кол" & Text.From(_)),

    // 8. Сборка финальной таблицы
    ResultTable = Table.FromRows(ВыровненныеСтроки, ИменаКолонок),
    ПовышенниеЗаголовков = Table.PromoteHeaders(ResultTable),
    Переименование1вТаблица = Table.RenameColumns(ПовышенниеЗаголовков,{{"1", "Таблица"}}),
    Нормализованные1 = fnRenameToCanonical(Переименование1вТаблица, СправочникКолонок, {"Таблица"}),
    ИзмененнияТипа = Table.TransformColumnTypes(Нормализованные1,{
        {"Таблица", Int64.Type}, 
        {"NПП", type text}, 
        {"NВЛСР", type text}, 
        {"НаименованиеРабот", type text}, 
        {"ЕдИзм", type text}, 
        {"КолВо", type number}, 
        {"СсылкаНаЧерСпе", type text}, 
        {"ФормулаРасРасОбъРабИРасМат", type text}
    }),
    УдалениеПервойСтроки = Table.Skip(ИзмененнияТипа,1),
    ДобавленРаздел = Table.AddColumn(УдалениеПервойСтроки, "Раздел", each let
    // 1. Берем текущую строку
    row = _,
    
    // 2. Получаем имена ВСЕХ колонок в таблице и вычитаем из них наши исключения
    otherColumns = List.Difference(Record.FieldNames(row), {"НаименованиеРабот", "Таблица"}),
    
    // 3. Достаем значения из оставшихся колонок
    otherValues = List.Transform(otherColumns, each Record.Field(row, _)),
    
    // 4. Оставляем только те значения, которые НЕ пустые (не null и не пустая строка "")
    nonEmptyValues = List.Select(otherValues, each _ <> null and _ <> ""),
    
    // 5. Если непустых значений 0 — значит, все остальные колонки пустые
    isAllOthersEmpty = List.Count(nonEmptyValues) = 0
in
    // Если все остальные пустые, и в Наименовании есть текст — возвращаем его
    if isAllOthersEmpty and row[НаименованиеРабот] <> null and row[НаименованиеРабот] <> "" 
    then row[НаименованиеРабот] 
    else null),
    ЗаполнениеВнизРаздел = Table.FillDown(ДобавленРаздел,{"Раздел"}),
        ДобавленУдалитьСтроку = Table.AddColumn(ЗаполнениеВнизРаздел, "Удалить_строку", each if [Раздел] = [НаименованиеРабот] then true else false),
    УдаленыСтрокиРазделов = Table.SelectRows(ДобавленУдалитьСтроку, each ([Удалить_строку] = false)),
    УдаленныеСтолбцы = Table.RemoveColumns(УдаленыСтрокиРазделов,{"Удалить_строку"}),

    ДобавленыСсылкиРазделенные = Table.AddColumn(УдаленныеСтолбцы, "СсылкиРазделенные", each let
    // Берем значение из нормализованной колонки (без запятых и пробелов)
    val = if [СсылкаНаЧерСпе] = null then "" else [СсылкаНаЧерСпе],
    
    // Убираем переносы строк, чтобы склеить разорванные ссылки
    flatVal = Text.Replace(Text.Replace(val, "#(lf)", " "), "#(cr)", " "),
    
    // Наш универсальный якорь
    prefix = "ЕСТ-ПМ-80825-Р-",
    
    // Разбиваем строку по якорю
    chunks = Text.Split(flatVal, prefix),
    
    // Первый элемент всегда пустой (то, что стоит до первого якоря), пропускаем его
    validChunks = List.Skip(chunks, 1),
    
    // Обрабатываем каждый кусок
    processed = List.Transform(validChunks, (chunk) =>
        let
            // Возвращаем префикс на место
            fullChunk = prefix & Text.Trim(chunk),
            upperChunk = Text.Upper(fullChunk),
            
            // Если есть .СО — это спецификация
            hasSpec = Text.Contains(upperChunk, ".СО"),
            
            // Проверяем, есть ли в куске и чертеж, и спецификация (если писали в одну строку без префикса)
            hasDrawInSpec = hasSpec and (Text.Contains(upperChunk, ". Л.") or Text.Contains(upperChunk, ".Л.")),
            posSpec = if hasSpec then Text.PositionOf(upperChunk, ".СО") else -1,
            
            // Если смешанный кусок, делим его по .СО
            drawPart = if hasDrawInSpec and posSpec > 0 then Text.Start(fullChunk, posSpec)
                       else if not hasSpec then fullChunk
                       else null,
                       
            specPart = if hasDrawInSpec then 
                           let 
                               // Вытаскиваем префикс из начала строки, чтобы приклеить к спецификации
                               prefixPart = Text.Start(fullChunk, Text.PositionOf(fullChunk, ".")) 
                           in prefixPart & Text.Range(fullChunk, posSpec, Text.Length(fullChunk) - posSpec)
                       else if hasSpec then fullChunk
                       else null
        in
            [
                Draw = if drawPart <> null then Text.TrimEnd(Text.TrimStart(drawPart, ",")) else null, 
                Spec = if specPart <> null then Text.Trim(specPart) else null
            ]
    ),
    
    // Собираем очищенные списки чертежей и спецификаций
    draws = List.Select(List.Transform(processed, each _[Draw]), each _ <> null and _ <> ""),
    specs = List.Select(List.Transform(processed, each _[Spec]), each _ <> null and _ <> ""),
    
    // Склеиваем обратно с переносом строки
    finalDraw = if List.IsEmpty(draws) then null else Text.Combine(draws, "#(lf)"),
    finalSpec = if List.IsEmpty(specs) then null else Text.Combine(specs, "#(lf)")
in
    [Чертежи = finalDraw, Спецификации = finalSpec]),
    #"Развернутый элемент СсылкиРазделенные" = Table.ExpandRecordColumn(ДобавленыСсылкиРазделенные, "СсылкиРазделенные", {"Чертежи", "Спецификации"}, {"Чертежи", "Спецификации"}),
    #"Переупорядоченные столбцы" = Table.ReorderColumns(#"Развернутый элемент СсылкиРазделенные",{"Таблица", "NПП", "NВЛСР", "НаименованиеРабот", "ЕдИзм", "КолВо", "СсылкаНаЧерСпе", "Чертежи", "Спецификации", "ФормулаРасРасОбъРабИРасМат", "Раздел"}),
    УдаленСсылкаНаЧерСпе = Table.RemoveColumns(#"Переупорядоченные столбцы", {"СсылкаНаЧерСпе"}),

    // ==========================================
    // 1. РАЗДЕЛЕНИЕ СТОЛБЦА "Чертежи"
    // ==========================================
    ДобавленоШифрЛисты = Table.AddColumn(УдаленСсылкаНаЧерСпе, "РазделенныеЧертежи", each fnParseChertezhi([Чертежи])),
    ОчищеноШифрЛисты = ДобавленоШифрЛисты,
    РазвернутоЧертежи = Table.ExpandRecordColumn(ОчищеноШифрЛисты, "РазделенныеЧертежи", {"ШифрРД", "ЛистыРД"}),
    УдаленЧертежи = Table.RemoveColumns(РазвернутоЧертежи, {"Чертежи"}),
    // УдаленЧертежи = РазвернутоЧертежи,

    // ==========================================
    // 2. РАЗДЕЛЕНИЕ СТОЛБЦА "Спецификации"
    // ==========================================
    ДобавленоШифрЛистыСО = Table.AddColumn(УдаленЧертежи, "РазделенныеСпец", each fnParseSpec([Спецификации])),
    РазвернутоСпец = Table.ExpandRecordColumn(ДобавленоШифрЛистыСО, "РазделенныеСпец", {"ШифрРДСО", "ЛистыРДСО"}),
    ПереупорядРДСО = Table.ReorderColumns(РазвернутоСпец,{"Таблица", "NПП", "NВЛСР", "НаименованиеРабот", "ЕдИзм", "КолВо", "ШифрРД", "ЛистыРД", "Спецификации", "ШифрРДСО", "ЛистыРДСО", "ФормулаРасРасОбъРабИРасМат", "Раздел"}),
    УдаленСпецификации = Table.RemoveColumns(ПереупорядРДСО, {"Спецификации"}),

    // ==========================================
    // 3. ОБЪЕДИНЕНИЕ ШИФРОВ (ШифрРД + ШифрРДСО) с заполнением по таблице
    // ==========================================
    
    // 3.1 Сливаем ШифрРД и ШифрРДСО; пустые значения превращаем в null,
    //     чтобы Table.FillDown мог их "протянуть"
    ДобавленОбъединенныйШифр = Table.AddColumn(УдаленСпецификации, "ШифрОбъединенный", each 
        let
            v = if [ШифрРД] = null or [ШифрРД] = "" then [ШифрРДСО] else [ШифрРД]
        in
            if v = null or v = "" then null else v),
    
    // 3.2 Индекс для восстановления исходного порядка строк после Group
    ДобавленИндекс = Table.AddIndexColumn(ДобавленОбъединенныйШифр, "Индекс", 0, 1),
    
    // 3.3 Обрабатываем каждую Таблицу изолированно
    ЗаполненоПоТаблицам = Table.Group(
        ДобавленИндекс, 
        {"Таблица"}, 
        {{"Данные", each 
            let
                // FillDown покрывает все строки начиная с первой непустой
                заполненныйВниз = Table.FillDown(_, {"ШифрОбъединенный"}),
                
                // Первое непустое значение таблицы — им добьём "головные" nulls
                значения = List.RemoveNulls(Table.Column(заполненныйВниз, "ШифрОбъединенный")),
                первоеЗначение = if List.IsEmpty(значения) then null else значения{0},
                
                заполненная = 
                    if первоеЗначение = null then 
                        заполненныйВниз   // вся таблица без шифров — оставляем null
                    else 
                        Table.TransformColumns(
                            заполненныйВниз, 
                            {{"ШифрОбъединенный", each if _ = null then первоеЗначение else _}}
                        )
            in
                заполненная,
            type table}}),
    
    // 3.4 Разворачиваем обратно (все исходные колонки, кроме группового ключа)
    КолонкиВнутри = List.Difference(Table.ColumnNames(ДобавленИндекс), {"Таблица"}),
    Развернуто = Table.ExpandTableColumn(
        ЗаполненоПоТаблицам, "Данные", КолонкиВнутри, КолонкиВнутри),
    
    // 3.5 Восстанавливаем исходный порядок строк
    Отсортировано = Table.Sort(Развернуто, {{"Индекс", Order.Ascending}}),
    УдаленИндекс = Table.RemoveColumns(Отсортировано, {"Индекс"}),
    
    // 3.6 Удаляем исходные ШифрРД и ШифрРДСО, объединённую переименовываем
    УдаленыИсходныеШифры = Table.RemoveColumns(УдаленИндекс, {"ШифрРД", "ШифрРДСО"}),
    ПереименованШифр = Table.RenameColumns(УдаленыИсходныеШифры, {{"ШифрОбъединенный", "ШифрРД"}}),
    
    // 3.7 Финальный порядок колонок
    ФинальныйПорядок = Table.ReorderColumns(
        ПереименованШифр, 
        {"Таблица", "NПП", "NВЛСР", "НаименованиеРабот", "ЕдИзм", "КолВо", 
         "ШифрРД", "ЛистыРД", "ЛистыРДСО", "ФормулаРасРасОбъРабИРасМат", "Раздел"}),

    // ==========================================
    // 3.8 Валидация символов (неблокирующее предупреждение)
    // ==========================================
    ДобавленоПредупреждение = Table.AddColumn(ФинальныйПорядок, "Предупреждение", each
        let
            okRD = fnOnlyAllowedChars([ЛистыРД], "0123456789,"),
            okRDSO = fnOnlyAllowedChars([ЛистыРДСО], "0123456789,."),
            msgs = List.RemoveNulls({
                if okRD then null 
                    else "ЛистыРД: " & Text.From([ЛистыРД]),
                if okRDSO then null 
                    else "ЛистыРДСО: " & Text.From([ЛистыРДСО])
            })
        in
            if List.IsEmpty(msgs) then null else Text.Combine(msgs, " | ")
    )

in
    ДобавленоПредупреждение