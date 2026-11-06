(ZIPFile as binary) =>
let
    Source = Binary.Buffer(ZIPFile),
    Size = Binary.Length(Source),
    
    Unsigned16LE = BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16, ByteOrder.LittleEndian),
    Unsigned32LE = BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger32, ByteOrder.LittleEndian),
    
    // 1. Находим EOCD (End of Central Directory)
    EOCD_Data = fnBinaryRange(Source, Size - 22, 22),
    EOCD_Signature = Unsigned32LE(EOCD_Data),
    EOCD_Offset = if EOCD_Signature = 101010256 then Unsigned32LE(fnBinaryRange(Source, Size - 6, 4)) else error "Не найден EOCD.",
    CD_Size = Unsigned32LE(fnBinaryRange(Source, Size - 10, 4)),
    
    // 2. Читаем Central Directory
    CentralDirectoryHeader = BinaryFormat.Record([
        VersionMade = Unsigned16LE,
        VersionNeed = Unsigned16LE,
        Flags = Unsigned16LE,
        Compression = Unsigned16LE,
        ModTime = Unsigned16LE,
        ModDate = Unsigned16LE,
        CRC32 = Unsigned32LE,
        CompressedSize = Unsigned32LE,
        UncompressedSize = Unsigned32LE,
        FileNameLength = Unsigned16LE,
        ExtrasLength = Unsigned16LE,
        FileCommentLength = Unsigned16LE,
        DiskNumberStarts = Unsigned16LE,
        InternalFileAttributes = Unsigned16LE,
        ExternalFileAttributes = Unsigned32LE,
        LocalHeaderOffset = Unsigned32LE
    ]),
    
    CentralHeaderFormatter = BinaryFormat.Choice(
        Unsigned32LE,
        each if _ <> 33639248 then // 0x02014b50 - сигнатура заголовка
            BinaryFormat.Record([IsValid = false])
        else
            BinaryFormat.Choice(
                BinaryFormat.Binary(42), // Фиксированная часть заголовка
                (headerBytes) =>
                    let h = CentralDirectoryHeader(headerBytes) in
                    BinaryFormat.Record([
                        IsValid = true,
                        LocalHeaderOffset = h[LocalHeaderOffset],
                        CompressedSize = h[CompressedSize],
                        Filename = BinaryFormat.Binary(h[FileNameLength]),
                        Extras = BinaryFormat.Binary(h[ExtrasLength]),
                        Comment = BinaryFormat.Binary(h[FileCommentLength])
                    ]),
                type binary
            )
    ),
    
    // 3. Добавляем 200 нулевых байт в конец, чтобы List не падал с ошибкой EOF
    CentralDirBytes = fnBinaryRange(Source, EOCD_Offset, CD_Size),
    PaddedBytes = Binary.FromList(List.Combine({Binary.ToList(CentralDirBytes), List.Repeat({0}, 200)})),
    
    Files = BinaryFormat.List(CentralHeaderFormatter, each _[IsValid] = true)(PaddedBytes),
    
    // 4. Фильтруем служебные записи, у которых нет поля "Filename"
    ValidFiles = List.Select(Files, each Record.HasFields(_, "Filename")),
    
    // 5. Извлекаем содержимое
    Extracted = List.Transform(ValidFiles, (file) =>
        let
            // Читаем имя файла как бинарник и конвертируем
            FileNameText = try Text.FromBinary(file[Filename], 65001) otherwise Text.FromBinary(file[Filename], 1252),
            
            // Вычисляем, где начинаются сами данные (пропускаем имя и extras локального заголовка)
            LocalNameLen = Unsigned16LE(fnBinaryRange(Source, file[LocalHeaderOffset] + 26, 2)),
            LocalExtraLen = Unsigned16LE(fnBinaryRange(Source, file[LocalHeaderOffset] + 28, 2)),
            DataStart = file[LocalHeaderOffset] + 30 + LocalNameLen + LocalExtraLen,
            
            CompressedData = fnBinaryRange(Source, DataStart, file[CompressedSize]),
            
            // ХАК: Добавляем нули в конец для лечения ошибки Deflate
            PaddedData = Binary.FromList(List.Combine({Binary.ToList(CompressedData), {0,0,0,0}})),
            
            Content = try Binary.Buffer(Binary.Decompress(PaddedData, Compression.Deflate)) 
                      otherwise try Binary.Buffer(Binary.Decompress(CompressedData, Compression.Deflate)) 
                      otherwise null
        in
            [FileName = FileNameText, Content = Content]
    ),
    
    ResultTable = Table.FromRecords(Extracted)
in
    ResultTable