(filePath as text) =>
    let
        Source = File.Contents(filePath),
        
        // 1. Распаковка и парсинг документа
        Extracted = try fxZipExtractAll(Source) otherwise null,
        DocumentXml = if Extracted = null then null else Extracted{[FileName="word/document.xml"]}[Content],
        XmlRecord = if DocumentXml = null then null else Xml.Document(DocumentXml),
        
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
                                txt = Text.Trim(fnExtractText(cell), {" ", "#(lf)", "#(cr)"}),
                                span = fnGetGridSpan(cell),
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
        ПовышениеЗаголовков = Table.PromoteHeaders(ResultTable),
        ТаблицаСЗаголовками = Table.RenameColumns(ПовышениеЗаголовков,{{"1", "Таблица"}}),
        Нормализованные1 = fnRenameToCanonical(ТаблицаСЗаголовками, СправочникКолонок, {"Таблица"}),
        ИзмененияТипа = Table.TransformColumnTypes(Нормализованные1,{
            {"Таблица", Int64.Type}, 
            {"NПП", type text}, 
            {"NВЛСР", type text}, 
            {"НаименованиеРабот", type text}, 
            {"ЕдИзм", type text}, 
            {"КолВо", type number}, 
            {"СсылкаНаЧерСпе", type text}, 
            {"ФормулаРасРасОбъРабИРасМат", type text}
        }),
        УдалениеПервойСтроки = Table.Skip(ИзмененияТипа,1),
        СРазделом = fnAddSectionColumn(УдалениеПервойСтроки),
        ДобавленУдалитьСтроку = Table.AddColumn(СРазделом, "Удалить_строку", each if [Раздел] = [НаименованиеРабот] then true else false),
        УдаленыСтрокиРазделов = Table.SelectRows(ДобавленУдалитьСтроку, each ([Удалить_строку] = false)),
        УдаленныеСтолбцы = Table.RemoveColumns(УдаленыСтрокиРазделов,{"Удалить_строку"}),

        ДобавленыСсылкиРазделенные = Table.AddColumn(УдаленныеСтолбцы, "СсылкиРазделенные", each fnSplitReferences([СсылкаНаЧерСпе], Prefix)),
        #"Развернутый элемент СсылкиРазделенные" = Table.ExpandRecordColumn(ДобавленыСсылкиРазделенные, "СсылкиРазделенные", {"Чертежи", "Спецификации"}, {"Чертежи", "Спецификации"}),
        #"Переупорядоченные столбцы" = Table.ReorderColumns(#"Развернутый элемент СсылкиРазделенные",{"Таблица", "NПП", "NВЛСР", "НаименованиеРабот", "ЕдИзм", "КолВо", "СсылкаНаЧерСпе", "Чертежи", "Спецификации", "ФормулаРасРасОбъРабИРасМат", "Раздел"}),
        УдаленСсылкаНаЧерСпе = Table.RemoveColumns(#"Переупорядоченные столбцы", {"СсылкаНаЧерСпе"}),

        // ==========================================
        // 1. РАЗДЕЛЕНИЕ СТОЛБЦА "Чертежи"
        // ==========================================
        ДобавленоШифрЛисты = Table.AddColumn(УдаленСсылкаНаЧерСпе, "РазделенныеЧертежи", each fnParseChertezhi([Чертежи])),
        РазвернутоЧертежи = Table.ExpandRecordColumn(ДобавленоШифрЛисты, "РазделенныеЧертежи", {"ШифрРД", "ЛистыРД"}),
        УдаленЧертежи = Table.RemoveColumns(РазвернутоЧертежи, {"Чертежи"}),

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
  
        ДобавленоИмяФайла = Table.AddColumn(ПереименованШифр, "ИмяФайла", each List.Last(Text.Split(filePath, "\")), type text),

        ФинальныйПорядок = Table.ReorderColumns(
            ДобавленоИмяФайла, 
            {"ИмяФайла", "Таблица", "NПП", "NВЛСР", "НаименованиеРабот", "ЕдИзм", "КолВо", 
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
            ),

        Результат = if XmlRecord = null then 
                        #table({"ИмяФайла", "Предупреждение"}, {{filePath, "Не удалось распаковать docx (повреждён ZIP)"}})
                    else 
                        ДобавленоПредупреждение // ваш финальный шаг
    in
        Результат