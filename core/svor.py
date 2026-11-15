"""СВОР: строки с количеством по проекту (П) и по РД (Р), статус изменения и цвет выделения в docx.

Разведка (РД/, 40 СВОР): цвет бывает цветом шрифта (красный FF0000, зелёный 00B050) или подсветкой (cyan);
в большинстве СВОР Изм.1 (Нов.) цвета нет вообще. Красный - позиция удалена или изменена, зелёный - новая,
у скорректированной строки часто красным выделено только отклонение. Поэтому статус считается по числам,
а цвет только сохраняется в поле "Цвет". В "Замечание" идёт лишь явное противоречие (зелёный, но не новая)
и отклонение, не равное Р-П. Красный в Изм.2 бывает и у новых по числам строк (изменение относительно Изм.1),
поэтому «красный» замечаний не даёт; в СВОР без цвета его отсутствие не замечание.

Строка: {"Раздел", "Номер", "Наименование", "Ед", "П", "Р", "Откл", "Примечание", "Статус", "Цвет", "Замечание"}.
"""
import re
import zipfile
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_NO_COLOR = {None, "000000", "auto", "333333", "FFFFFF"}
RED, GREEN = "FF0000", "00B050"


def _num(text):
    s = (text or "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def status_by_numbers(p, r):
    """Статус по количеству: новая / удалена / изменена / без изменений; пусто, если чисел нет."""
    p, r = p or 0.0, r or 0.0
    if p == 0 and r == 0:
        return ""
    if p == 0:
        return "новая"
    if r == 0:
        return "удалена"
    return "без изменений" if p == r else "изменена"


def color_of_runs(colors):
    """Один цвет строки: красный / зелёный / подсветка / пусто. Красный и зелёный сразу - 'смешанный'."""
    cs = {c for c in colors if c not in _NO_COLOR}
    if RED in cs and GREEN in cs:
        return "смешанный"
    if RED in cs:
        return "красный"
    if GREEN in cs:
        return "зелёный"
    if any(str(c).startswith("hl:") for c in cs):
        return "подсветка"
    return ""


def _key(name, p, r):
    alnum = re.sub(r"[^0-9a-zа-я]", "", (name or "").lower().replace("ё", "е"))[:12]
    return alnum, p, r


def read_row_colors(path):
    """Цвета строк таблиц docx: {ключ строки: [цвет, ...]} в порядке появления (ключ - имя, П, Р)."""
    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    out = {}
    for tbl in root.iter(W + "tbl"):
        for tr in tbl.iter(W + "tr"):
            cells = tr.findall(W + "tc")
            if len(cells) < 6:
                continue
            texts, colors = [], []
            for tc in cells:
                texts.append("".join(t.text or "" for t in tc.iter(W + "t")))
                for run in tc.iter(W + "r"):
                    if not "".join(t.text or "" for t in run.findall(W + "t")).strip():
                        continue
                    rp = run.find(W + "rPr")
                    if rp is None:
                        continue
                    c = rp.find(W + "color")
                    if c is not None:
                        colors.append(c.get(W + "val"))
                    h = rp.find(W + "highlight")
                    if h is not None:
                        colors.append("hl:" + h.get(W + "val"))
            key = _key(texts[1], _num(texts[3]), _num(texts[4]))
            out.setdefault(key, []).append(color_of_runs(colors))
    return out


def _column(headers, stage):
    for i, h in enumerate(headers):
        if h.startswith("Кол-во") and "(стадия %s)" % stage in h:
            return i
    return None


def classify(rows):
    """Добавляет Статус и Замечание: цвет должен подходить к числам."""
    for r in rows:
        r["Статус"] = status_by_numbers(r["П"], r["Р"])
        notes = []
        if r["Откл"] is not None and r["П"] is not None and r["Р"] is not None \
                and abs((r["Р"] - r["П"]) - r["Откл"]) > 1e-6:
            notes.append("отклонение не равно Р-П")
        c, s = r["Цвет"], r["Статус"]
        if c == "зелёный" and s not in ("новая", ""):
            notes.append("зелёный, но по числам не новая")
        r["Замечание"] = "; ".join(notes)
    return rows


def read_svor(path):
    """Строки СВОР из docx. Строка раздела (есть наименование, нет чисел и единицы) задаёт "Раздел"."""
    from core.parsers.docx_parser import extract_tables_from_docx
    from core.parsers.header_profiles import parse_table

    colors = read_row_colors(path)
    out = []
    for table in extract_tables_from_docx(path):
        pt = parse_table(table)
        h = pt.headers
        ip, ir = _column(h, "П"), _column(h, "Р")
        iname = next((i for i, x in enumerate(h) if x.startswith("Наименование")), None)
        iunit = next((i for i, x in enumerate(h) if x.startswith("Ед")), None)
        inum = next((i for i, x in enumerate(h) if x.startswith("№")), None)
        idev = next((i for i, x in enumerate(h) if x.startswith("Разница")), None)
        inote = next((i for i, x in enumerate(h) if x.startswith("Примечание")), None)
        if None in (ip, ir, iname):
            continue
        section = ""
        for r in pt.rows:
            p, q = _num(r[ip]), _num(r[ir])
            name = r[iname].strip()
            unit = r[iunit].strip() if iunit is not None else ""
            if p is None and q is None and not unit:
                if name:
                    section = name
                continue
            queue = colors.get(_key(name, p, q))
            color = queue.pop(0) if queue else ""
            out.append({"Раздел": section, "Номер": r[inum].strip() if inum is not None else "", "Наименование": name,
                        "Ед": unit, "П": p, "Р": q, "Откл": _num(r[idev]) if idev is not None else None,
                        "Примечание": r[inote].strip() if inote is not None else "", "Цвет": color})
    return classify(out)
