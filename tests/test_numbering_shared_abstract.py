import zipfile

from core.parsers.numbering_fix import numbering_fixed

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

NUMBERING = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering {W}>
<w:abstractNum w:abstractNumId="9">
<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2"/></w:lvl>
<w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2.%3."/></w:lvl>
</w:abstractNum>
<w:num w:numId="25"><w:abstractNumId w:val="9"/></w:num>
<w:num w:numId="27"><w:abstractNumId w:val="9"/></w:num>
</w:numbering>"""


def _p(num_id, ilvl, text, hidden=False):
    rpr = "<w:rPr><w:vanish/></w:rPr>" if hidden else ""
    return (
        f'<w:p><w:pPr><w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{num_id}"/></w:numPr>{rpr}</w:pPr>'
        f"<w:r><w:t>{text}</w:t></w:r></w:p>"
    )


def _row(*paragraphs):
    return f"<w:tr><w:tc>{''.join(paragraphs)}</w:tc></w:tr>"


def _build(path):
    body = (
        "<w:tbl>"
        + _row(_p(25, 1, "a"))
        + _row(_p(25, 1, "b"))
        + _row(_p(25, 0, "", hidden=True), _p(25, 1, "kit1"))
        + _row(_p(27, 2, "c1"))
        + _row(_p(27, 2, "c2"))
        + _row(_p(25, 1, "kit2"))
        + _row(_p(27, 2, "d1"))
        + "</w:tbl>"
    )
    document = f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{body}<w:sectPr/></w:body></w:document>'
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/numbering.xml", NUMBERING)


def test_numids_share_counters_of_one_abstract_num(tmp_path):
    """Как в Word: numId с общим abstractNum делят счётчики, пропущенный старший уровень считается начатым."""
    from docx import Document

    path = tmp_path / "shared.docx"
    _build(str(path))
    with numbering_fixed(str(path)) as fixed:
        table = Document(fixed).tables[0]
        cells = [row.cells[0].text.split()[0] for row in table.rows]
    assert cells == ["1.1", "1.2", "2.1", "2.1.1", "2.1.2", "2.2", "2.2.1"]
