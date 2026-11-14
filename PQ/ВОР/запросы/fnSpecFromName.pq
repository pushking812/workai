(наименование as any) as text =>
let
    // Позиции спецификации (СО), указанные прямо в наименовании работ:
    // "см. спец. Поз. 73", "(ЕСТ-...СО (поз. 11.4-11.6))", "поз. 12.14, 12.15", "Поз.58-64".
    // Разбор номеров и диапазонов делает fnParseSpec (подставляем «.СО» перед номерами).
    t = Text.Replace(Text.Replace(Text.Replace(Text.Replace(Text.Lower(if наименование = null then "" else Text.From(наименование)),
        "ё", "е"), ", ", ","), "#(00A0)", " "), "–", "-"),
    части = List.Skip(Text.Split(t, "поз"), 1),
    Цифры = {"0".."9"},
    Допустимые = {"0".."9", ",", ".", "-"},
    // после «поз» допускаются остатки слова («иции»), точка, пробелы и «№»; затем должна идти цифра
    Номера = (s as text) as text =>
        let
            начало = Text.TrimStart(s, {" ", ".", "№", "и", "ц", "я", "ю", "е", "й"}),
            симв = Text.ToList(начало),
            пробег = Text.Combine(List.FirstN(симв, each List.Contains(Допустимые, _)), "")
        in
            if List.IsEmpty(симв) or not List.Contains(Цифры, симв{0}) then "" else пробег,
    найдено = List.Transform(части, each fnParseSpec(".СО " & Номера(_))[NППРДСО]),
    все = List.Distinct(List.Select(List.Combine(List.Transform(найдено, each Text.Split(_, ","))), each _ <> ""))
in
    Text.Combine(все, ",")
