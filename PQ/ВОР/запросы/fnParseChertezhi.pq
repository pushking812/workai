(inputText as any) =>
let
    // Разбор по строкам: список записей [Шифр, Листы]
    parsed = fnParseChertezhiLines(inputText),
    
    // Уникальные НЕПУСТЫЕ шифры (порядок сохраняется)
    uniqueShifrs = List.Distinct(
        List.Select(List.Transform(parsed, each _[Шифр]), each _ <> "")
    ),
    
    // Все листы из всех строк — разбиваем по запятой и склеиваем уникальные
    allSheets = List.Distinct(
        List.Select(
            List.Combine(List.Transform(parsed, each Text.Split(_[Листы], ","))),
            each _ <> ""
        )
    ),
    
    finalShifr = Text.Combine(uniqueShifrs, "#(lf)"),
    finalListy = Text.Combine(allSheets, ",")
in
    [ШифрРД = finalShifr, ЛистыРД = finalListy]
