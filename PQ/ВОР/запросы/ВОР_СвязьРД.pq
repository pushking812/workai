let
    // Связь ВОР - реестр чертежей РД (один ко многим): одна строка на пару "шифр РД + лист".
    // Пары берутся построчно из исходного текста ссылок, поэтому лист не теряет свой шифр.
    Source = ВОР_База,
    Есть = Table.SelectRows(Source, each [Чертежи] <> null and [Чертежи] <> ""),
    Ключи = Table.SelectColumns(Есть, {"ИдСтроки", "ШифрПроекта", "Чертежи"}),
    Пары = Table.AddColumn(Ключи, "Пара", each fnParseChertezhiLines([Чертежи]), type list),
    ПарыРазвернуты = Table.ExpandListColumn(Пары, "Пара"),
    БезТекста = Table.RemoveColumns(ПарыРазвернуты, {"Чертежи"}),
    Запись = Table.ExpandRecordColumn(БезТекста, "Пара", {"Шифр", "Листы"}, {"ШифрРД", "Листы"}),
    ЕстьШифр = Table.SelectRows(Запись, each [ШифрРД] <> null and [ШифрРД] <> "" and [Листы] <> null),
    СписокЛистов = Table.AddColumn(ЕстьШифр, "Лист", each List.Distinct(List.Select(Text.Split([Листы], ","), each _ <> "")), type list),
    ЛистыРазвернуты = Table.ExpandListColumn(СписокЛистов, "Лист"),
    БезЛистов = Table.RemoveColumns(ЛистыРазвернуты, {"Листы"}),
    Непустые = Table.SelectRows(БезЛистов, each [Лист] <> null),
    КлючРД = Table.AddColumn(Непустые, "КлючРД", each [ШифрРД] & "|" & [Лист], type text),
    Типы = Table.TransformColumnTypes(КлючРД, {{"ИдСтроки", type text}, {"ШифрПроекта", type text}, {"ШифрРД", type text}, {"Лист", type text}})
in
    Типы
