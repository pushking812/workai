(inputText as any) =>
let
    val = if inputText = null then "" else Text.From(inputText),
    pos = Text.PositionOfAny(val, {".", ",", "/", " ", ":", ";"}, Occurrence.First),
    shifr = if pos > -1 then Text.Trim(Text.Start(val, pos)) else Text.Trim(val),
    listyRaw = if pos > -1 then Text.Middle(val, pos + 1) else "",
    
    step1 = Text.Replace(Text.Replace(Text.Replace(listyRaw, "(", ","), ")", ","), ".", ","),
    step2 = Text.Select(step1, {"0".."9", ",", "-"}),
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