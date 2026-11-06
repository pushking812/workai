(inputText as any) =>
let
    val = if inputText = null then "" else Text.From(inputText),
    
    // Замена Text.PositionOfAny — ищем минимум из позиций через Text.PositionOf
    pos = 
        let
            positions = List.RemoveNulls(
                List.Transform(
                    {".", ",", "/", " ", ":", ";"},
                    each 
                        let p = Text.PositionOf(val, _, Occurrence.First) 
                        in if p = -1 then null else p
                )
            )
        in
            if List.IsEmpty(positions) then -1 else List.Min(positions),
    
    shifr = if pos > -1 then Text.Trim(Text.Start(val, pos)) else Text.Trim(val),
    listyRaw = if pos > -1 then Text.Range(val, pos + 1, Text.Length(val) - pos - 1) else "",
    
    step1 = Text.Replace(Text.Replace(Text.Replace(listyRaw, "(", ","), ")", ","), ".", ","),
    
    // Замена Text.Select — оставляем только разрешённые символы
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
    [ШифрРД = shifr, ЛистыРД = finalListyText]