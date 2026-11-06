// Запрос ФайлBinary
let
    Source = File.Contents(FilePath),
    
    // 1. Распаковка и парсинг документа
    Extracted = fxZipExtractAll(Source),
    DocumentXml = Extracted{[FileName="word/document.xml"]}[Content],
    XmlRecord = Xml.Document(DocumentXml),
    
    // 2. Универсальный поиск узлов
    FindNodes = (node as any, tag as text) as list =>
        let
            res = if node is record then
                      let
                          isMatch = if Record.HasFields(node, "Name") and Text.EndsWith(node[Name], tag) then {node} else {},
                          childTable = if Record.HasFields(node, "Value") and node[Value] is table then node[Value]
                                       else if Record.HasFields(node, "Table") and node[Table] is table then node[Table]
                                       else null,
                          children = if childTable <> null then
                                         List.Combine(List.Transform(Table.ToRecords(childTable), each @FindNodes(_, tag)))
                                     else {}
                      in
                          isMatch & children
                  else if node is table then
                      List.Combine(List.Transform(Table.ToRecords(node), each @FindNodes(_, tag)))
                  else
                      {}
        in
            res,

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
            tcPr = FindNodes(cell, "tcPr"),
            gridSpans = if List.Count(tcPr) > 0 then FindNodes(tcPr{0}, "gridSpan") else {},
            spanVal = if List.Count(gridSpans) > 0 then 
                          let 
                              attrs = gridSpans{0}[Attributes],
                              val = try Record.Field(attrs, "w:val") otherwise try Record.Field(attrs, "val") otherwise "1"
                          in Number.FromText(val)
                      else 1
        in
            spanVal,

    // 5. Находим ВСЕ таблицы в документе
    AllTables = FindNodes(XmlRecord, "tbl"),

    // 6. Обрабатываем каждую таблицу отдельно (добавляем TableID)
    ProcessedTables = List.Transform(List.Positions(AllTables), (tblIndex) =>
        let
            currentTable = AllTables{tblIndex},
            rows = FindNodes(currentTable, "tr"),
            processedRows = List.Transform(rows, (row) =>
                let
                    cells = FindNodes(row, "tc"),
                    // Для каждой ячейки: извлекаем текст и проверяем gridSpan
                    cellData = List.Transform(cells, (cell) =>
                        let
                            txt = Text.Trim(ExtractText(cell), {" ", "#(lf)", "#(cr)"}),
                            span = GetGridSpan(cell),
                            // Добиваем пустыми значениями, если ячейка объединена
                            padded = {txt} & List.Repeat({""}, span - 1)
                        in
                            [Texts = padded, HasNum = List.Count(FindNodes(cell, "numPr")) > 0]
                    ),
                    // Склеиваем ячейки с учетом gridSpan
                    flatTexts = List.Combine(List.Transform(cellData, each [Texts])),
                    hasNum = if List.Count(cellData) > 0 then cellData{0}[HasNum] else false
                in
                    [TableID = tblIndex + 1, Texts = flatTexts, HasNum = hasNum]
            )
        in
            processedRows
    ),
    
    AllRowData = List.Combine(ProcessedTables),

    // 7. Расставляем авто-номера (изолированно для каждой таблицы)
    NumberedRows = List.Accumulate(
        AllRowData,
        [Counter = 0, Result = {}],
        (state, current) =>
            let
                // Сбрасываем счетчик при переходе на новую таблицу
                currentCounter = if current[TableID] <> (if List.Count(state[Result]) > 0 then List.Last(state[Result])[TableID] else current[TableID]) then 0 else state[Counter],
                newCounter = if current[HasNum] then currentCounter + 1 else currentCounter,
                texts = current[Texts],
                newTexts = if current[HasNum] and List.Count(texts) > 0 then 
                               {Text.From(newCounter)} & List.Skip(texts, 1)
                           else texts
            in
                [Counter = newCounter, Result = state[Result] & { [TableID = current[TableID], Texts = newTexts] }]
    )[Result],

    // 8. Динамическое выравнивание (Ваш код)
    МаксКолонок = List.Max(List.Transform(NumberedRows, each List.Count(_[Texts]))),
    ВыровненныеСтроки = List.Transform(NumberedRows, each {_[TableID]} & _[Texts] & List.Repeat({""}, МаксКолонок - List.Count(_[Texts]))),
    ИменаКолонок = {"Таблица"} & List.Transform({1..МаксКолонок}, each "Кол" & Text.From(_)),

    // 9. Сборка финальной таблицы
    ResultTable = Table.FromRows(ВыровненныеСтроки, ИменаКолонок),
    ПовышенниеЗаголовков = Table.PromoteHeaders(ResultTable),
    Переименование1вТаблица = Table.RenameColumns(ПовышенниеЗаголовков,{{"1", "Таблица"}}),
    ИзмененнияТипа = Table.TransformColumnTypes(Переименование1вТаблица,{{"Таблица", Int64.Type}, {"№#(lf)п/п", Int64.Type}, {"№ в ЛСР", Int64.Type}, {"Наименование работ", type text}, {"Ед.#(lf)изм.", type text}, {"Кол-во", type number}, {"Ссылка на чертежи, спецификации", type text}, {"Формула расчета, расчет объемов работ и расхода материалов", type text}}),
    УдалениеПервойСтроки = Table.Skip(ИзмененнияТипа,1),
    ДобавленРаздел = Table.AddColumn(УдалениеПервойСтроки, "Раздел", each let
    // 1. Берем текущую строку
    row = _,
    
    // 2. Получаем имена ВСЕХ колонок в таблице и вычитаем из них наши исключения
    otherColumns = List.Difference(Record.FieldNames(row), {"Наименование работ", "Таблица"}),
    
    // 3. Достаем значения из оставшихся колонок
    otherValues = List.Transform(otherColumns, each Record.Field(row, _)),
    
    // 4. Оставляем только те значения, которые НЕ пустые (не null и не пустая строка "")
    nonEmptyValues = List.Select(otherValues, each _ <> null and _ <> ""),
    
    // 5. Если непустых значений 0 — значит, все остальные колонки пустые
    isAllOthersEmpty = List.Count(nonEmptyValues) = 0
in
    // Если все остальные пустые, и в Наименовании есть текст — возвращаем его
    if isAllOthersEmpty and row[Наименование работ] <> null and row[Наименование работ] <> "" 
    then row[Наименование работ] 
    else null),
    ЗаполнениеВнизРаздел = Table.FillDown(ДобавленРаздел,{"Раздел"}),
    ДобавленУдалитьСтроку = Table.AddColumn(ЗаполнениеВнизРаздел, "Удалить_строку", each if [Раздел] = [Наименование работ] then true else false),
    УдаленыСтрокиРазделов = Table.SelectRows(ДобавленУдалитьСтроку, each ([Удалить_строку] = false)),
    УдаленныеСтолбцы = Table.RemoveColumns(УдаленыСтрокиРазделов,{"Удалить_строку"}),
    // Новый шаг нормализации имен
    НормализованныеИмена = 
let
    ИсходныеИмена = Table.ColumnNames(УдаленныеСтолбцы),
    НовыеИмена = List.Transform(
        ИсходныеИмена,
        (colName) =>
            let
                cleanName0 = Text.Replace(Text.Replace(Text.Replace(colName, "#(lf)", " "), "#(cr)", " "), "#(tab)", " "),
                cleanName = Text.Replace(cleanName0, "№", "N"),
                words = List.Select(Text.SplitAny(cleanName, " ,-_./\:;()«»"), each _ <> ""),
                capitalized = List.Transform(
                    words, 
                    each if Text.Length(_) > 1 then Text.Upper(Text.Start(_, 1)) & Text.Range(_, 1, Text.Length(_) - 1) else Text.Upper(_)
                ),
                combined = Text.Combine(capitalized, ""),
                result = if Text.Length(combined) > 20 then
                            let
                                firstWord = capitalized{0},
                                otherWords = List.Transform(List.Skip(capitalized, 1), each Text.Start(_, 3)),
                                shortened = Text.Combine(List.InsertRange(otherWords, 0, {firstWord}), "")
                            in shortened
                         else combined
            in result
    ),
    // Ручная сборка списка пар через индексы — без List.Zip
    Пары = List.Transform(
        List.Positions(ИсходныеИмена),
        (i) => {ИсходныеИмена{i}, НовыеИмена{i}}
    )
in
    Table.RenameColumns(УдаленныеСтолбцы, Пары),
    ДобавленыСсылкиРазделенные = Table.AddColumn(НормализованныеИмена, "СсылкиРазделенные", each let
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
    ДобавленРеконструкция = Table.AddColumn(#"Переупорядоченные столбцы", "Реконструкция", each if [Чертежи] = null and [Спецификации] = null then null 
else Text.Combine(List.RemoveNulls({[Чертежи], [Спецификации]}), " ")),
    ДобавленПроверка = Table.AddColumn(ДобавленРеконструкция, "Проверка", each let
    // Берем оригинал (уже нормализованный) и реконструкцию
    orig = if [СсылкаНаЧерСпе] = null then "" else Text.From([СсылкаНаЧерСпе]),
    recon = if [Реконструкция] = null then "" else [Реконструкция],
    
    // Очищаем обе строки от пробелов, переносов и табуляции
    clean = (t) => Text.Replace(Text.Replace(Text.Replace(t, " ", ""), "#(lf)", ""), "#(cr)", ""),
    origClean = clean(orig),
    reconClean = clean(recon)
in
    origClean = reconClean),

    // 1. Проверяем, есть ли в колонке "Проверка" хотя бы одно значение FALSE
    ЕстьОшибки = List.Contains(Table.Column(ДобавленПроверка, "Проверка"), false),

    // 2. Если ошибки есть - вызываем предупреждение (запрос упадет с ошибкой)
    //    Если ошибок нет - удаляем технические колонки и отдаем чистые данные
    ЧистыйРезультат = if ЕстьОшибки 
                      then error "ВНИМАНИЕ! При разбиении ссылок произошла потеря данных. Свяжитесь с разработчиком." 
                      else Table.RemoveColumns(ДобавленПроверка, {"Реконструкция", "Проверка"}),
    УдаленСсылкаНаЧерСпе = Table.RemoveColumns(ЧистыйРезультат,{"СсылкаНаЧерСпе"}),

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
    УдаленСпецификации = Table.RemoveColumns(ПереупорядРДСО, {"Спецификации"})

in
    УдаленСпецификации