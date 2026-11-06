(node as any, tag as text) as list =>
let
    res = if node is record then
              let
                  isMatch = if Record.HasFields(node, "Name") and Text.EndsWith(node[Name], tag) then {node} else {},
                  childTable = if Record.HasFields(node, "Value") and node[Value] is table then node[Value]
                               else if Record.HasFields(node, "Table") and node[Table] is table then node[Table]
                               else null,
                  children = if childTable <> null then
                                 List.Combine(List.Transform(Table.ToRecords(childTable), each fnFindNodes(_, tag)))
                             else {}
              in
                  isMatch & children
          else if node is table then
              List.Combine(List.Transform(Table.ToRecords(node), each fnFindNodes(_, tag)))
          else
              {}
in
    res