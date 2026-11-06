(filePath as text) =>
let
    // 1. Оборачиваем ВСЮ логику в try
    Результат = try (
        let
            Source = File.Contents(filePath),
            
            Extracted = fxZipExtractAllCentral(Source),
            DocumentXml = Extracted{[FileName="word/document.xml"]}[Content],
            DocumentXmlBuffered = Binary.Buffer(DocumentXml),
            XmlRecord = Xml.Document(DocumentXmlBuffered),
            
            AllTables = fnFindNodes(XmlRecord, "tbl"),
            
            ProcessedTables = List.Transform(List.Positions(AllTables), (tblIndex) =>
                let
                    currentTable = AllTables{tblIndex},
                    rows = fnFindNodes(currentTable, "tr"),
                    processedRows = List.Transform(rows, (row) =>
                        let
                            cells = fnFindNodes(row, "tc"),
                            cellData = List.Transform(cells, (cell) =>
                                let
                                    txt = Text.Trim(fnExtractText(cell), {" ", "#(lf)", "#(cr)"}),
                                    span = fnGetGridSpan(cell),
                                    padded = {txt} & List.Repeat({""}, span - 1)
                                in
                                    [Texts = padded]
                            ),
                            flatTexts = List.Combine(List.Transform(cellData, each [Texts]))
                        in
                            [TableID = tblIndex + 1, Texts = flatTexts]
                    )
                in
                    processedRows
            ),
            
            AllRowData = List.Combine(ProcessedTables),
            
            МаксКолонок = List.Max(List.Transform(AllRowData, each List.Count(_[Texts]))),
            ВыровненныеСтроки = List.Transform(AllRowData, each {_[TableID]} & _[Texts] & List.Repeat({""}, МаксКолонок - List.Count(_[Texts]))),
            ИменаКолонок = {"Таблица"} & List.Transform({1..МаксКолонок}, each "Кол" & Text.From(_)),
            
            ResultTable = Table.FromRows(ВыровненныеСтроки, ИменаКолонок),
            ПовышенниеЗаголовков = Table.PromoteHeaders(ResultTable),
            Переименование1вТаблица = Table.RenameColumns(ПовышенниеЗаголовков,{{"1", "Таблица"}}),
            
            Нормализованные1 = fnRenameToCanonical(Переименование1вТаблица, СправочникКолонок, {"Таблица"}),
            
            // 1. Безопасно приводим "КолВо" к числу (заменяем запятые на точки)
            БезопасноеКолВо = Table.TransformColumns(Нормализованные1, {
                {"КолВо", each 
                    let 
                        s = Text.Replace(Text.From(_), ",", "."),
                        num = try Number.From(s) otherwise null
                    in num, type number}
            }),
            
            // 2. Приводим остальные колонки к нужным типам (без КолВо)
            ИзмененнияТипа = Table.TransformColumnTypes(БезопасноеКолВо,{
                {"Таблица", Int64.Type}, 
                {"NПП", type text}, 
                {"NВЛСР", type text}, 
                {"НаименованиеРабот", type text}, 
                {"ЕдИзм", type text}, 
                {"СсылкаНаЧерСпе", type text}, 
                {"ФормулаРасРасОбъРабИРасМат", type text}
            }),
            
            УдалениеПервойСтроки = Table.Skip(ИзмененнияТипа,1),
            
            СРазделом = fnAddSectionColumn(УдалениеПервойСтроки),
            
            ДобавленУдалитьСтроку = Table.AddColumn(СРазделом, "Удалить_строку", each if [Раздел] = [НаименованиеРабот] then true else false),
            УдаленыСтрокиРазделов = Table.SelectRows(ДобавленУдалитьСтроку, each ([Удалить_строку] = false)),
            УдаленныеСтолбцы = Table.RemoveColumns(УдаленыСтрокиРазделов,{"Удалить_строку"}),
            
            ДобавленыСсылкиРазделенные = Table.AddColumn(УдаленныеСтолбцы, "СсылкиРазделенные", each fnSplitReferences([СсылкаНаЧерСпе], Prefix)),
            #"Развернутый элемент СсылкиРазделенные" = Table.ExpandRecordColumn(ДобавленыСсылкиРазделенные, "СсылкиРазделенные", {"Чертежи", "Спецификации"}, {"Чертежи", "Спецификации"}),
            #"Переупорядоченные столбцы" = Table.ReorderColumns(#"Развернутый элемент СсылкиРазделенные",{"Таблица", "NПП", "NВЛСР", "НаименованиеРабот", "ЕдИзм", "КолВо", "СсылкаНаЧерСпе", "Чертежи", "Спецификации", "ФормулаРасРасОбъРабИРасМат", "Раздел"}),
            УдаленСсылкаНаЧерСпе = Table.RemoveColumns(#"Переупорядоченные столбцы",{"СсылкаНаЧерСпе"}),
            
            ДобавленоШифрЛисты = Table.AddColumn(УдаленСсылкаНаЧерСпе, "РазделенныеЧертежи", each fnParseChertezhi([Чертежи])),
            РазвернутоЧертежи = Table.ExpandRecordColumn(ДобавленоШифрЛисты, "РазделенныеЧертежи", {"ШифрРД", "ЛистыРД"}),
            УдаленЧертежи = Table.RemoveColumns(РазвернутоЧертежи, {"Чертежи"}),
            
            ДобавленоШифрЛистыСО = Table.AddColumn(УдаленЧертежи, "РазделенныеСпец", each fnParseSpec([Спецификации])),
            РазвернутоСпец = Table.ExpandRecordColumn(ДобавленоШифрЛистыСО, "РазделенныеСпец", {"ШифрРДСО", "ЛистыРДСО"}),
            ПереупорядРДСО = Table.ReorderColumns(РазвернутоСпец,{"Таблица", "NПП", "NВЛСР", "НаименованиеРабот", "ЕдИзм", "КолВо", "ШифрРД", "ЛистыРД", "Спецификации", "ШифрРДСО", "ЛистыРДСО", "ФормулаРасРасОбъРабИРасМат", "Раздел"}),
            УдаленСпецификации = Table.RemoveColumns(ПереупорядРДСО, {"Спецификации"}),
            
            ДобавленОбъединенныйШифр = Table.AddColumn(УдаленСпецификации, "ШифрОбъединенный", each 
                let v = if [ШифрРД] = null or [ШифрРД] = "" then [ШифрРДСО] else [ШифрРД]
                in if v = null or v = "" then null else v),
            ДобавленИндекс = Table.AddIndexColumn(ДобавленОбъединенныйШифр, "Индекс", 0, 1),
            ЗаполненоПоТаблицам = Table.Group(ДобавленИндекс, {"Таблица"}, {{"Данные", each 
                let
                    заполненныйВниз = Table.FillDown(_, {"ШифрОбъединенный"}),
                    значения = List.RemoveNulls(Table.Column(заполненныйВниз, "ШифрОбъединенный")),
                    первоеЗначение = if List.IsEmpty(значения) then null else значения{0},
                    заполненная = if первоеЗначение = null then заполненныйВниз else Table.TransformColumns(заполненныйВниз, {{"ШифрОбъединенный", each if _ = null then первоеЗначение else _}})
                in заполненная, type table}}),
            КолонкиВнутри = List.Difference(Table.ColumnNames(ДобавленИндекс), {"Таблица"}),
            Развернуто = Table.ExpandTableColumn(ЗаполненоПоТаблицам, "Данные", КолонкиВнутри, КолонкиВнутри),
            Отсортировано = Table.Sort(Развернуто, {{"Индекс", Order.Ascending}}),
            УдаленИндекс = Table.RemoveColumns(Отсортировано, {"Индекс"}),
            
            УдаленыИсходныеШифры = Table.RemoveColumns(УдаленИндекс, {"ШифрРД", "ШифрРДСО"}),
            ПереименованШифр = Table.RenameColumns(УдаленыИсходныеШифры, {{"ШифрОбъединенный", "ШифрРД"}}),
            
            ДобавленоИмяФайла = Table.AddColumn(ПереименованШифр, "ИмяФайла", each List.Last(Text.Split(filePath, "\")), type text),
            
            ФинальныйПорядок = Table.ReorderColumns(
                ДобавленоИмяФайла, 
                {"ИмяФайла", "Таблица", "NПП", "NВЛСР", "НаименованиеРабот", "ЕдИзм", "КолВо", 
                 "ШифрРД", "ЛистыРД", "ЛистыРДСО", "ФормулаРасРасОбъРабИРасМат", "Раздел"}),
                 
            ДобавленоПредупреждение = Table.AddColumn(ФинальныйПорядок, "Предупреждение", each
                let
                    okRD = fnOnlyAllowedChars([ЛистыРД], "0123456789,"),
                    okRDSO = fnOnlyAllowedChars([ЛистыРДСО], "0123456789,."),
                    msgs = List.RemoveNulls({
                        if okRD then null else "ЛистыРД: " & Text.From([ЛистыРД]),
                        if okRDSO then null else "ЛистыРДСО: " & Text.From([ЛистыРДСО])
                    })
                in
                    if List.IsEmpty(msgs) then null else Text.Combine(msgs, " | ")
            )
        in
            ДобавленоПредупреждение
    ), // Запятая здесь закрывает присвоение Результат
    
    // 2. Блок обработки ошибок обернут в скобки ( ) для безопасности синтаксиса
    ОбработкаОшибки = if Результат[HasError] then 
        (
            let
                errReason = try Text.From(Результат[Error][Reason]) otherwise "",
                errMessage = try Text.From(Результат[Error][Message]) otherwise "",
                errDetail = try Text.From(Результат[Error][Detail]) otherwise "",
                
                fullErrorText = "ОШИБКА: " & errMessage & 
                                (if errDetail <> "" then " | Подробности: " & errDetail else "")
            in
                #table(
                    {"ИмяФайла", "Предупреждение"}, 
                    {{ List.Last(Text.Split(filePath, "\")), fullErrorText }}
                )
        )
    else 
        Результат[Value]
in
    ОбработкаОшибки // <--- Финальный in для самой функции