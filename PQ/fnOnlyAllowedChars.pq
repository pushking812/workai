(inputText as any, allowed as text) as logical =>
let
    s = if inputText = null then "" else Text.From(inputText),
    invalid = List.Select(
        Text.ToList(s),
        each Text.PositionOf(allowed, _) < 0
    )
in
    List.IsEmpty(invalid)