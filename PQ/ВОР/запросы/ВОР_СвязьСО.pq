let
    // Связь ВОР - СО (один ко многим): одна строка на каждый номер из NППРДСО.
    // Версия документа определяется тройкой: шифр проекта, номер изменения, дата изменения.
    // Ключ = ШифрПроекта | НомИзмПроекта | ДатаИзм (гггг-мм-дд) | NПП. У таблицы СО должен быть такой же ключ.
    Source = ФайлBinary,
    Есть = Table.SelectRows(Source, each [NППРДСО] <> null and [NППРДСО] <> ""),
    Ключи = Table.SelectColumns(Есть, {"ИдСтроки", "ШифрПроекта", "НомИзмПроекта", "ДатаИзм", "NППРДСО"}),
    Номера = Table.AddColumn(Ключи, "NПП", each
        List.Distinct(List.Select(Text.Split([NППРДСО], ","), each _ <> "" and fnOnlyAllowedChars(_, "0123456789."))), type list),
    // Номера без точек по краям (как NПП в СО): "12." -> "12", ".4.15" -> "4.15" (остаток от "п.4.15")
    БезТочек = Table.TransformColumns(Номера, {{"NПП", each List.Distinct(List.Select(List.Transform(_, each Text.Trim(_, ".")), each _ <> "")), type list}}),
    Развернуто = Table.ExpandListColumn(БезТочек, "NПП"),
    БезСписка = Table.RemoveColumns(Развернуто, {"NППРДСО"}),
    Непустые = Table.SelectRows(БезСписка, each [NПП] <> null),
    КлючСО = Table.AddColumn(Непустые, "КлючСО", each
        (if [ШифрПроекта] = null then "" else [ШифрПроекта]) & "|"
        & (if [НомИзмПроекта] = null then "" else Text.From([НомИзмПроекта])) & "|"
        & (if [ДатаИзм] = null then "" else Date.ToText([ДатаИзм], "yyyy-MM-dd")) & "|"
        & [NПП], type text),
    Типы = Table.TransformColumnTypes(КлючСО, {{"ИдСтроки", type text}, {"ШифрПроекта", type text}, {"NПП", type text}})
in
    Типы
