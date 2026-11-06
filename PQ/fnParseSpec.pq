(inputText as any) =>
let
    val = if inputText = null then "" else Text.From(inputText),
    posCO = Text.PositionOf(Text.Upper(val), ".СО"),
    shifr = if posCO > -1 then Text.Trim(Text.Start(val, posCO)) else Text.Trim(val),
    listyRaw = if posCO > -1 then Text.Middle(val, posCO + 3) else "",
    
    firstDigit = Text.PositionOfAny(listyRaw, {"0".."9"}),
    listyCut = if firstDigit > -1 then Text.Middle(listyRaw, firstDigit) else Text.Trim(listyRaw),
    step1_fixed = Text.Replace(Text.Replace(Text.Replace(listyCut, "(", ","), ")", ","), ".", "."), 
    step2 = Text.Select(step1_fixed, {"0".."9", ",", "-", "."}),
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