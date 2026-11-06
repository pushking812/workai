(inputText as any) =>
let
    val = if inputText = null then "" else Text.From(inputText),
    lines = List.Select(Text.Split(val, "#(lf)"), each Text.Trim(_) <> ""),
    
    ProcessLine = (line as text) as record =>
        let
            pos = 
                let
                    positions = List.RemoveNulls(
                        List.Transform(
                            {".", ",", "/", " ", ":", ";"},
                            each 
                                let p = Text.PositionOf(line, _, Occurrence.First) 
                                in if p = -1 then null else p
                        )
                    )
                in
                    if List.IsEmpty(positions) then -1 else List.Min(positions),
            
            shifr = if pos > -1 then Text.Trim(Text.Start(line, pos)) else Text.Trim(line),
            listyRaw = if pos > -1 then Text.Range(line, pos + 1, Text.Length(line) - pos - 1) else "",
            
            step1 = Text.Replace(Text.Replace(Text.Replace(listyRaw, "(", ","), ")", ","), ".", ","),
            step2 = Text.Combine(
                List.Select(
                    Text.ToList(step1),
                    each Text.PositionOf("0123456789,-", _) >= 0
                ),
                ""
            ),
            step2_clean = Text.Replace(Text.Replace(step2, ",-", "-"), "-,", "-"),
            step3 = List.Select(Text.Split(step2_clean, ","), each _ <> ""),
            cleaned = Text.Combine(step3, ","),
            
            Expanded = List.Combine(
                List.Transform(Text.Split(cleaned, ","), (item) =>
                    let
                        parts = Text.Split(item, "-"),
                        count = List.Count(parts)
                    in
                        if count = 2 then
                            let
                                s = try Number.FromText(parts{0}) otherwise null,
                                e = try Number.FromText(parts{1}) otherwise null
                            in
                                if s <> null and e <> null and e >= s then
                                    List.Transform(List.Numbers(s, e - s + 1), each Text.From(_))
                                else
                                    {item}
                        else
                            {item}
                )
            ),
            finalListyText = Text.Combine(Expanded, ",")
        in
            [Шифр = shifr, Листы = finalListyText],
    
    parsed = List.Transform(lines, ProcessLine),
    
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