(inputText as any) =>
let
    val = if inputText = null then "" else Text.From(inputText),
    posCO = Text.PositionOf(Text.Upper(val), ".СО"),
    shifr = if posCO > -1 then Text.Trim(Text.Start(val, posCO)) else Text.Trim(val),
    listyRaw = if posCO > -1 then Text.Range(val, posCO + 3, Text.Length(val) - posCO - 3) else "",
    
    // Замена Text.PositionOfAny — ищем первый встреченный цифровой символ
    firstDigit = 
        let
            positions = List.RemoveNulls(
                List.Transform(
                    {"0".."9"},
                    each 
                        let p = Text.PositionOf(listyRaw, _, Occurrence.First) 
                        in if p = -1 then null else p
                )
            )
        in
            if List.IsEmpty(positions) then -1 else List.Min(positions),
    
    listyCut = if firstDigit > -1 then Text.Range(listyRaw, firstDigit, Text.Length(listyRaw) - firstDigit) else Text.Trim(listyRaw),
    step1_fixed = Text.Replace(Text.Replace(Text.Replace(listyCut, "(", ","), ")", ","), ".", "."), 
    
    // Замена Text.Select — разрешены цифры, запятая, дефис и точка
    step2 = Text.Combine(
        List.Select(
            Text.ToList(step1_fixed),
            each Text.PositionOf("0123456789,-.", _) >= 0
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
                        startParts = Text.Split(parts{0}, "."),
                        endParts = Text.Split(parts{1}, "."),
                        prefixStart = List.RemoveLastN(startParts, 1),
                        prefixEnd = List.RemoveLastN(endParts, 1),
                        isSameLevel = (prefixStart = prefixEnd)
                    in
                        if isSameLevel then
                            let
                                s = try Number.FromText(List.Last(startParts)) otherwise null,
                                e = try Number.FromText(List.Last(endParts)) otherwise null
                            in
                                if s <> null and e <> null and e >= s then
                                    let
                                        prefixStr = if List.IsEmpty(prefixStart) then "" else Text.Combine(prefixStart, ".") & ".",
                                        nums = List.Numbers(s, e - s + 1)
                                    in
                                        List.Transform(nums, each prefixStr & Text.From(_))
                                else
                                    {item}
                        else
                            {"ОШИБКА_УРОВНЕЙ(" & item & ")"}
                else
                    {item}
        )
    ),
    finalListyText = Text.Combine(Expanded, ",")
in
    [ШифрРДСО = shifr, ЛистыРДСО = finalListyText]