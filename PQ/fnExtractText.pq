(node as record) as text =>
let
    name = node[Name],
    isText = Text.EndsWith(name, "t"),
    isBreak = Text.EndsWith(name, "br") or Text.EndsWith(name, "cr"),
    isPara = Text.EndsWith(name, "p"),
    val = if Record.HasFields(node, "Value") and node[Value] is text then node[Value] else "",
    currentText = if isText then val else if isBreak then "#(lf)" else "",
    childTable = if Record.HasFields(node, "Value") and node[Value] is table then node[Value]
                 else if Record.HasFields(node, "Table") and node[Table] is table then node[Table]
                 else null,
    childrenText = if childTable <> null then
                       Text.Combine(List.Transform(Table.ToRecords(childTable), each fnExtractText(_)), "")
                   else "",
    result = currentText & childrenText & (if isPara and not isText and childrenText <> "" then "#(lf)" else "")
in
    result