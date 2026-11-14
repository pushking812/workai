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
            listyCut = if firstDigit > -1 then Text.Range(listyRaw, firstDigit, Text.Length(listyRaw) - firstDigit) else "",
            step1 = Text.Replace(Text.Replace(listyCut, "(", ","), ")", ","),
            step2 = Text.Combine(
                List.Select(
                    Text.ToList(step1),
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
                                s = try Number.FromText(List.Last(startParts)) otherwise null,
                                e = try Number.FromText(List.Last(endParts)) otherwise null,
                                prefixStr = if List.IsEmpty(prefixStart) then "" else Text.Combine(prefixStart, ".") & "."
                            in
                                if prefixStart = prefixEnd and s <> null and e <> null and e >= s then
                                    List.Transform(List.Numbers(s, e - s + 1), each prefixStr & Text.From(_))
                                else
                                    {item}
                        else
                            {item}
                )
            ),
            finalListyText = Text.Combine(Expanded, ",")
        in
            [Шифр = shifr, Листы = finalListyText],
    
    parsed = List.Transform(lines, ProcessLine)
in
    parsed
