(ZIPFile) =>
let
    Header = BinaryFormat.Record([
        MiscHeader = BinaryFormat.Binary(14),
        BinarySize = BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger32, ByteOrder.LittleEndian),
        FileSize = BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger32, ByteOrder.LittleEndian),
        FileNameLen = BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16, ByteOrder.LittleEndian),
        ExtrasLen = BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16, ByteOrder.LittleEndian)
    ]),
    HeaderChoice = BinaryFormat.Choice(
        BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger32, ByteOrder.LittleEndian),
        each if _ <> 67324752 then
            BinaryFormat.Record([IsValid = false, Filename = null, Content = null])
        else
            BinaryFormat.Choice(
                BinaryFormat.Binary(26),
                each BinaryFormat.Record([
                    IsValid = true,
                    Filename = BinaryFormat.Text(Header(_)[FileNameLen]),
                    Extras = BinaryFormat.Text(Header(_)[ExtrasLen]),
                    Content = BinaryFormat.Transform(
                        BinaryFormat.Binary(Header(_)[BinarySize]),
                        (x) => try Binary.Buffer(Binary.Decompress(x, Compression.Deflate)) otherwise null
                    )
                ]),
                type binary
            )
    ),
    ZipFormat = BinaryFormat.List(HeaderChoice, each _[IsValid] = true),
    Entries = List.Transform(List.RemoveLastN(ZipFormat(ZIPFile), 1), (e) => [FileName = e[Filename], Content = e[Content]]),
    FilesTable = Table.FromRecords(Entries)
in
    FilesTable