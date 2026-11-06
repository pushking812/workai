(ZipFile as binary) =>
let
    ZipFileBuffer = Binary.Buffer(ZipFile),
    ZipFileSize = Binary.Length(ZipFileBuffer),
    
    CentralHeaderSignature = 0x02014b50,
    CentralHeaderSize = 42,
    LocalHeaderSize = 30,
    
    Unsigned16BitLittleEndian = BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16, ByteOrder.LittleEndian),
    Unsigned32BitLittleEndian = BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger32, ByteOrder.LittleEndian),
    
    CentralDirectoryHeader = BinaryFormat.Record([
        Version = Unsigned16BitLittleEndian,
        VersionNeeded = Unsigned16BitLittleEndian,
        GeneralPurposeFlag = Unsigned16BitLittleEndian,
        CompressionMethod = Unsigned16BitLittleEndian,
        LastModifiedTime = Unsigned16BitLittleEndian,
        LastModifiedDate = Unsigned16BitLittleEndian,
        CRC32 = Unsigned32BitLittleEndian,
        CompressedSize = Unsigned32BitLittleEndian,
        UncompressedSize = Unsigned32BitLittleEndian,
        FileNameLength = Unsigned16BitLittleEndian,
        ExtrasLength = Unsigned16BitLittleEndian,
        FileCommentLength = Unsigned16BitLittleEndian,
        DiskNumberStarts = Unsigned16BitLittleEndian,
        InternalFileAttributes = Unsigned16BitLittleEndian,
        ExternalFileAttributes = Unsigned32BitLittleEndian,
        LocalHeaderOffset = Unsigned32BitLittleEndian
    ]),
    
    EndOfCentralDirectoryRecord = BinaryFormat.Record([
        RestOfFile = BinaryFormat.Binary(ZipFileSize - 22),
        EOCDsignature = Unsigned32BitLittleEndian,
        NumberOfThisDisk = Unsigned16BitLittleEndian,
        DiskWhereCentralDirectoryStarts = Unsigned16BitLittleEndian,
        NumberOfRecordsOnThisDisk = Unsigned16BitLittleEndian,
        TotalNumberOfRecords = Unsigned16BitLittleEndian,
        CentralDirectorySize = Unsigned32BitLittleEndian,
        OffsetToStart = Unsigned32BitLittleEndian
    ]),
    
    CentralHeaderFormatter = BinaryFormat.Choice(
        Unsigned32BitLittleEndian,
        each if _ <> CentralHeaderSignature then
            BinaryFormat.Record([LocalHeaderOffset = null, CompressedSize = null, FileNameLength = null, HeaderSize = null, IsValid = false, Filename = null])
        else
            BinaryFormat.Choice(
                BinaryFormat.Binary(CentralHeaderSize),
                each BinaryFormat.Record([
                    LocalHeaderOffset = CentralDirectoryHeader(_)[LocalHeaderOffset],
                    CompressedSize = CentralDirectoryHeader(_)[CompressedSize],
                    FileNameLength = CentralDirectoryHeader(_)[FileNameLength],
                    HeaderSize = LocalHeaderSize + CentralDirectoryHeader(_)[FileNameLength] + CentralDirectoryHeader(_)[ExtrasLength],
                    IsValid = true,
                    Filename = BinaryFormat.Text(CentralDirectoryHeader(_)[FileNameLength])
                ]),
                type binary
            )
    ),
    
    EOCDR = EndOfCentralDirectoryRecord(ZipFileBuffer),
    CentralDirectory = fnBinaryRange( ZipFileBuffer, EOCDR[OffsetToStart] ),
    CentralDirectoryFormatter = BinaryFormat.List(CentralHeaderFormatter, each _[IsValid] = true),
    
    FilesTable = Table.FromRecords(List.RemoveLastN(CentralDirectoryFormatter(CentralDirectory), 1)),
    
    // Исправленный блок ResultTable:
    ResultTable = Table.AddColumn(FilesTable, "Content", each 
        Binary.Decompress(
            fnBinaryRange( ZipFileBuffer, [LocalHeaderOffset] + [HeaderSize], [CompressedSize] ), 
            Compression.Deflate 
        )
    ),
    
    FinalTable = Table.SelectColumns(ResultTable, {"Filename", "Content"}),
    Renamed = Table.RenameColumns(FinalTable, {{"Filename", "FileName"}})
in
    Renamed