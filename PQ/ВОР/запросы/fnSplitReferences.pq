(inputText as any, optional prefixParam as nullable text) as record =>
let
    // Якорь: обязательный аргумент, обычно передаётся из глобального параметра Prefix
    prefix = if prefixParam = null or prefixParam = "" then 
                 error "fnSplitReferences: не задан префикс (prefixParam). Проверьте параметр Prefix." 
             else prefixParam,
    
    // Готовим входное значение
    val = if inputText = null then "" else Text.From(inputText),
    flatVal = Text.Replace(Text.Replace(val, "#(lf)", " "), "#(cr)", " "),
    
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
    [Чертежи = finalDraw, Спецификации = finalSpec]
