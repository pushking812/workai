(cell as record) as number =>
let
    tcPr = fnFindNodes(cell, "tcPr"),
    gridSpans = if List.Count(tcPr) > 0 then fnFindNodes(tcPr{0}, "gridSpan") else {},
    spanVal = if List.Count(gridSpans) > 0 then 
                  let 
                      attrs = gridSpans{0}[Attributes],
                      val = try Record.Field(attrs, "w:val") otherwise try Record.Field(attrs, "val") otherwise "1"
                  in Number.FromText(val)
              else 1
in
    spanVal