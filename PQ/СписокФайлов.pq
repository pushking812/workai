let
    // 1. Если ЗадатьДиректорию = 1, сканируем папку
    ИзДиректории = 
        if ЗадатьДиректорию = 1 then
            let
                Source = Folder.Files(РабочаяДиректория),
                Filtered = Table.SelectRows(Source, each [Extension] = ".docx" and not Text.StartsWith([Name], "~$")),
                Selected = Table.SelectColumns(Filtered, {"Folder Path", "Name"}),
                AddedPath = Table.AddColumn(Selected, "ПолныйПуть", each [Folder Path] & [Name])
            in
                Table.SelectColumns(AddedPath, {"ПолныйПуть"})
        else
            null,
            
    // 2. Если ЗадатьДиректорию = 0, берем из таблицы СписокВОР
    ИзТаблицы = 
        if ЗадатьДиректорию = 0 then
            let
                Source = Excel.CurrentWorkbook(){[Name="СписокВОР"]}[Content],
                // Оставляем только строки, где Загружать = 1
                Filtered = Table.SelectRows(Source, each [Загружать] = 1),
                // Собираем полный путь (если путь относительный, клеим к РабочейДиректории)
                AddedPath = Table.AddColumn(Filtered, "ПолныйПуть", each 
                    if Text.Contains([ПутьФайла], ":\") or Text.StartsWith([ПутьФайла], "\\") then [ПутьФайла]
                    else РабочаяДиректория & "\" & [ПутьФайла]
                )
            in
                Table.SelectColumns(AddedPath, {"ПолныйПуть"})
        else
            null,
            
    Итог = if ЗадатьДиректорию = 1 then ИзДиректории else ИзТаблицы
in
    Итог