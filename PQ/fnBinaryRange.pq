(binary as binary, offset as number, optional count as nullable number) as binary =>
let
    // Преобразуем бинарник в список байтов
    list = Binary.ToList(binary),
    // Берем нужный срез
    range = List.Range(list, offset, count),
    // Возвращаем обратно в бинарный формат
    result = Binary.FromList(range)
in
    result