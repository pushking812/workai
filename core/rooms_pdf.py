"""Разбор PDF с экспликациями помещений в таблицу записей.

Типы документов:
  1 — «Инвентаризационная ведомость помещений» (7 или 6 колонок: № по
      правоустанавливающим, № внутр., назначение, площади, подразделение,
      примечание). Может быть повёрнута (таблица транспонирована).
  2 — «Экспликация помещений N этажа» (№ пом, наименование, площадь,
      категория, кол-во чел.) с разделами-службами.
Текст берётся из текстового слоя. Если слоя нет (буквы — векторные контуры),
каждая ячейка сетки рисуется в картинку и распознаётся OCR (RapidOCR, модель для кириллицы); такие строки помечаются «OCR» и требуют проверки.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

OCR_DPI = 200
GRID_SETTINGS = {
    "vertical_strategy": "lines", "horizontal_strategy": "lines",
    "edge_min_length": 20, "snap_tolerance": 3, "join_tolerance": 3,
    "intersection_tolerance": 3,
}

FIELDS = [
    "Здание_код", "Здание", "Этаж_код", "Этаж_файл", "Лист", "Этаж_документ",
    "Наземный_подземный", "Раздел", "Номер_помещения", "Номер_правоуст",
    "Назначение", "Площадь_м2", "Площадь_правоуст_м2", "Категория",
    "Кол_чел", "Подразделение", "Примечание", "Тип_экспликации", "Файл",
    "Чтение", "Проверить",
]

# ключевые слова имени файла -> код здания в справочнике
BUILDING_KEYS = [
    (r"дом\s*связи", "ДС1"), (r"едцм", "ЗДЦ"), (r"фрунзенск", "ФСТ"),
    (r"институт\s*-\s*1", "ТИ1"), (r"институт\s*-\s*2", "ТИ2"),
    (r"невск", "НЕВ"), (r"сенн", "СЕН"),
]


@dataclass
class ParsedDoc:
    file: str
    kind: int = 0                 # тип экспликации 1 / 2 / 0 (не распознан)
    method: str = "текст"         # «текст» или «OCR»
    records: list = field(default_factory=list)
    checks: list = field(default_factory=list)   # сверка итогов документа
    notes: list = field(default_factory=list)


# ---------------------------------------------------------------- числа/текст
_CONFUSE = str.maketrans({"О": "0", "о": "0", "O": "0", "o": "0", "З": "3", "з": "3",
                          "l": "1", "I": "1", "|": "1", "б": "6", "Б": "6"})


def clean(s) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def parse_area(s, ocr: bool = False):
    """'2 077,7' / '12,78 м²' -> float; '-', '---', '' -> None."""
    t = clean(s).replace("м²", "").replace("кв.м", "").replace("м2", "")
    if ocr:
        t = t.translate(_CONFUSE)
    t = re.sub(r"\s+", "", t).replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", t):
        return None
    return float(t)


# ------------------------------------------------------- имя файла -> контекст
def file_context(path: Path) -> dict:
    stem = path.stem
    low = stem.lower()
    ctx = {"building": "", "floor_label": "", "sheet": "", "floor_kind": "", "floor_no": None}
    for pat, code in BUILDING_KEYS:
        if re.search(pat, low):
            ctx["building"] = code
            break
    part = stem.rsplit(". ", 1)[-1] if ". " in stem else stem
    m = re.search(r"_(л\d+)$", part, re.I)
    if m:
        ctx["sheet"] = m.group(1).lower()
        part = part[:m.start()]
    ctx["floor_label"] = part.strip()
    pl = part.lower()
    if "подвал" in pl:
        ctx["floor_kind"] = "подвал"
    elif "техничес" in pl:
        ctx["floor_kind"] = "тех"
    else:
        m = re.search(r"(-?\d+)\s*(подземн\w*)?\s*этаж", pl)
        if m:
            ctx["floor_no"] = int(m.group(1))
            ctx["floor_kind"] = "этаж"
    return ctx


def floor_code(building: str, ctx: dict) -> str:
    kind, no = ctx["floor_kind"], ctx["floor_no"]
    if building in ("ЗДЦ", "ДС1"):
        if kind == "тех":
            return "ЭТ"
        if kind == "подвал" or (kind == "этаж" and no == -1 and building == "ЗДЦ"):
            return "ЭП"
        if kind == "этаж" and no is not None and no >= 1:
            return f"Э{no}"
        return ""
    return "ПС" if building else ""


# ----------------------------------------------------------------- сетка
def _cluster(vals, tol=2.5):
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(g) / len(g) for g in out]


def _nearest(bounds, v):
    return min(range(len(bounds)), key=lambda i: abs(bounds[i] - v))


@dataclass
class Cell:
    r0: int
    r1: int
    c0: int
    c1: int
    bbox: tuple
    text: str = ""


def build_grid(page):
    """Ячейки главной таблицы страницы (с учётом объединённых)."""
    tables = page.find_tables(GRID_SETTINGS)
    if not tables:
        return None
    tbl = max(tables, key=lambda t: len(t.cells))
    xs = _cluster([c[0] for c in tbl.cells] + [c[2] for c in tbl.cells])
    ys = _cluster([c[1] for c in tbl.cells] + [c[3] for c in tbl.cells])
    cells = []
    for b in tbl.cells:
        r0, r1 = _nearest(ys, b[1]), _nearest(ys, b[3])
        c0, c1 = _nearest(xs, b[0]), _nearest(xs, b[2])
        if r1 > r0 and c1 > c0:
            cells.append(Cell(r0, r1, c0, c1, b))
    return xs, ys, cells


def build_grid_strict(page, min_share: float = 0.4, cover: float = 0.6):
    """Сетка только по длинным линиям — для векторных PDF, где буквы нарисованы
    контурами и дают короткие штрихи, похожие на границы столбцов.

    Граница принимается, если суммарная длина линий на ней >= min_share длины
    таблицы. Соседние ячейки объединяются, где линия между ними не покрывает
    cover ширины/высоты ячейки."""
    tables = page.find_tables(GRID_SETTINGS)
    if not tables:
        return None
    tx0, tt, tx1, tb = max(tables, key=lambda t: len(t.cells)).bbox
    W, H = tx1 - tx0, tb - tt
    vseg, hseg = [], []
    for e in page.edges:
        if e["orientation"] == "v" and e["x0"] >= tx0 - 3 and e["x1"] <= tx1 + 3:
            vseg.append((e["x0"], max(e["top"], tt), min(e["bottom"], tb)))
        elif e["orientation"] == "h" and e["top"] >= tt - 3 and e["bottom"] <= tb + 3:
            hseg.append((e["top"], max(e["x0"], tx0), min(e["x1"], tx1)))

    def union(ivs):
        ivs = sorted((a, b) for a, b in ivs if b > a)
        tot, cur = 0.0, None
        for a, b in ivs:
            if cur is None or a > cur[1]:
                if cur:
                    tot += cur[1] - cur[0]
                cur = [a, b]
            else:
                cur[1] = max(cur[1], b)
        return tot + (cur[1] - cur[0] if cur else 0.0)

    def good(segs, total):
        # граница — почти сплошная линия на всю таблицу; штрихи букв дают
        # прерывистые отрезки (покрытие ~50%) и отбрасываются
        out, group = [], []
        for s in sorted(segs):
            if group and s[0] - group[0][0] > 1.5:
                out.append(group)
                group = []
            group.append(s)
        if group:
            out.append(group)
        res = []
        for g in out:
            ivs = [(a, b) for _, a, b in g]
            span = max(b for _, b in ivs) - min(a for a, _ in ivs)
            if span >= min_share * total and union(ivs) >= 0.85 * span:
                res.append(sum(p for p, _, _ in g) / len(g))
        # близкие друг к другу кандидаты — одна граница
        return _cluster(res, 3.0)

    xs, ys = good(vseg, H), good(hseg, W)
    if len(xs) < 2 or len(ys) < 2:
        return None
    nr, nc = len(ys) - 1, len(xs) - 1

    def covered_v(ci, r):      # граница справа от столбца ci в строке r
        x = xs[ci + 1]
        tot = union([(max(a, ys[r]), min(b, ys[r + 1])) for p, a, b in vseg if abs(p - x) <= 3])
        return tot >= cover * (ys[r + 1] - ys[r])

    def covered_h(c, ri):      # граница под строкой ri в столбце c
        y = ys[ri + 1]
        tot = union([(max(a, xs[c]), min(b, xs[c + 1])) for p, a, b in hseg if abs(p - y) <= 3])
        return tot >= cover * (xs[c + 1] - xs[c])

    parent = list(range(nr * nc))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for r in range(nr):
        for c in range(nc):
            if c + 1 < nc and not covered_v(c, r):
                parent[find(r * nc + c)] = find(r * nc + c + 1)
            if r + 1 < nr and not covered_h(c, r):
                parent[find(r * nc + c)] = find((r + 1) * nc + c)
    groups = {}
    for r in range(nr):
        for c in range(nc):
            groups.setdefault(find(r * nc + c), []).append((r, c))
    cells = []
    for g in groups.values():
        r0, r1 = min(r for r, _ in g), max(r for r, _ in g) + 1
        c0, c1 = min(c for _, c in g), max(c for _, c in g) + 1
        cells.append(Cell(r0, r1, c0, c1, (xs[c0], ys[r0], xs[c1], ys[r1])))
    return xs, ys, cells


def _text_cell(page, bbox) -> str:
    x0, t, x1, b = bbox
    box = (max(x0 + 1, page.bbox[0]), max(t + 1, page.bbox[1]),
           min(x1 - 1, page.bbox[2]), min(b - 1, page.bbox[3]))
    if box[2] <= box[0] or box[3] <= box[1]:
        return ""
    return clean(page.crop(box, strict=False).extract_text() or "")


_ENGINE = None


def _ocr_engine():
    """RapidOCR (PP-OCRv5, восточнославянская модель), создаётся один раз."""
    global _ENGINE
    if _ENGINE is None:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
        _ENGINE = RapidOCR(params={
            "Rec.lang_type": LangRec.ESLAV, "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE, "Global.log_level": "error"})
    return _ENGINE


def _ocr_cells(page, cells):
    """OCR каждой непустой ячейки сетки (вырезка с белой рамкой)."""
    import numpy as np
    eng = _ocr_engine()
    img = np.array(page.to_image(resolution=OCR_DPI).original.convert("RGB"))
    k = OCR_DPI / 72.0
    ox, oy = page.bbox[0], page.bbox[1]
    pad = 24
    for c in cells:
        x0, t, x1, b = c.bbox
        px0, py0 = int((x0 - ox + 1.0) * k), int((t - oy + 1.0) * k)
        px1, py1 = int((x1 - ox - 1.0) * k), int((b - oy - 1.0) * k)
        if px1 - px0 < 6 or py1 - py0 < 6:
            continue
        crop = img[max(py0, 0):py1, max(px0, 0):px1]
        if int((crop.min(axis=2) < 150).sum()) < 10:    # пустая ячейка
            continue
        canvas = np.full((crop.shape[0] + 2 * pad, crop.shape[1] + 2 * pad, 3), 255, dtype=np.uint8)
        canvas[pad:pad + crop.shape[0], pad:pad + crop.shape[1]] = crop
        res = eng(canvas)
        if res.boxes is None:
            continue
        parts = []
        for box, txt in zip(res.boxes, res.txts):
            ys_ = [q[1] for q in box]
            parts.append((sum(ys_) / 4, sum(q[0] for q in box) / 4, max(ys_) - min(ys_), txt))
        parts.sort()
        lines, cur, last = [], [], None
        for cy, cx, h, txt in parts:        # строки внутри ячейки
            if last is not None and abs(cy - last) > 0.5 * h:
                lines.append(cur)
                cur = []
            cur.append((cx, txt))
            last = cy
        lines.append(cur)
        c.text = clean(" ".join(t for ln in lines for _, t in sorted(ln)))


def grid_matrix(page, ocr: bool):
    """Матрица текстов (строки x колонки) и признак «ячейка на всю ширину»."""
    g = (build_grid_strict(page) if ocr else None) or build_grid(page)
    if not g:
        return None, None, None
    xs, ys, cells = g
    if ocr:
        _ocr_cells(page, cells)
    else:
        for c in cells:
            c.text = _text_cell(page, c.bbox)
    nr, nc = len(ys) - 1, len(xs) - 1
    mat = [[""] * nc for _ in range(nr)]
    full = [False] * nr
    cont = set()   # (строка, колонка): продолжение объединённой по вертикали ячейки
    for c in cells:
        for r in range(c.r0, c.r1):
            for j in range(c.c0, c.c1):
                mat[r][j] = c.text
                if r > c.r0:
                    cont.add((r, j))
            if c.c0 == 0 and c.c1 == nc and nc > 1:
                full[r] = True
    return mat, full, cont


# ------------------------------------------------------------ сверка итогов
class _Sums:
    """Накопление сумм площади и сверка со строками «Итого»."""

    def __init__(self, doc: ParsedDoc):
        self.doc = doc
        self.blk = [0.0, 0.0]
        self.all = [0.0, 0.0]

    def add(self, fact, prav):
        for i, v in enumerate((fact, prav)):
            if v is not None:
                self.blk[i] += v
                self.all[i] += v

    def new_block(self):
        self.blk = [0.0, 0.0]

    def total(self, label, fact, prav):
        ok, msgs = True, []
        for i, (name, exp) in enumerate((("факт", fact), ("правоуст", prav))):
            if exp is None:
                continue
            good = abs(exp - self.blk[i]) < 0.06 or abs(exp - self.all[i]) < 0.06
            if not good:
                ok = False
            msgs.append(f"{name}: в документе {exp:g}, сумма {self.blk[i]:.2f} (всего {self.all[i]:.2f})")
        self.doc.checks.append({"Итого": label, "Совпало": "да" if ok else "НЕТ", "Детали": "; ".join(msgs)})
        self.blk = [0.0, 0.0]


# ------------------------------------------------------------------ тип 1
_TOTAL_RE = re.compile(r"^(итого|всего|общий итог)", re.I)


def _parse_ledger(mat, full, cont, doc: ParsedDoc, base: dict, ocr: bool):
    hdr = next((i for i, r in enumerate(mat) if any("назнач" in c.lower() for c in r)), None)
    if hdr is None:
        doc.notes.append("не найдена шапка таблицы")
        return
    ncol = len(mat[hdr])
    sums = _Sums(doc)
    section, floor_doc = "", ""
    for i in range(hdr + 1, len(mat)):
        vals = [clean(c) for c in mat[i]]
        if not any(vals):
            continue
        if full[i]:
            t = next(v for v in vals if v)
            if re.search(r"этаж", t, re.I):
                floor_doc, section = t, ""
            else:
                section = t
            sums.new_block()
            continue
        vals += [""] * (7 - len(vals))
        c0, c1, c2, c3, c4, c5 = vals[:6]
        c6 = vals[6] if ncol >= 7 else ""
        merged_note = ""
        for col in (3, 4):   # площадь объединённой ячейки считаем один раз (в первой строке)
            if (i, col) in cont and vals[col]:
                vals[col] = ""
                merged_note = "площадь в объединённой ячейке (учтена в первой строке)"
        c3, c4 = vals[3], vals[4]
        area_f, area_p = parse_area(c4, ocr), parse_area(c3, ocr)
        if _TOTAL_RE.match(c2) or _TOTAL_RE.match(c0):
            sums.total(c2 or c0, area_f, area_p)
            continue
        if not c0 and not c1 and not c2 and (c3 or c4):
            sums.total("(без подписи)", area_f, area_p)
            continue
        if not c0 and not c1 and c2 and not c3 and not c4:
            section = c2
            sums.new_block()
            continue
        sums.add(area_f, area_p)
        flags = [merged_note] if merged_note else []
        if (c3 not in ("", "-", "---") and area_p is None) or (c4 not in ("", "-", "---") and area_f is None):
            flags.append("площадь не число")
        if not c1:
            flags.append("нет внутр. номера")
        if ocr:
            flags.append("OCR")
        doc.records.append({**base, "Этаж_документ": floor_doc, "Раздел": section,
                            "Номер_помещения": c1, "Номер_правоуст": "" if set(c0) <= set("-–—") else c0,
                            "Назначение": c2, "Площадь_м2": area_f, "Площадь_правоуст_м2": area_p,
                            "Категория": "", "Кол_чел": "", "Подразделение": c5,
                            "Примечание": c6, "Тип_экспликации": 1, "Проверить": ", ".join(flags)})


def _parse_transposed(table, doc: ParsedDoc, base: dict):
    """Ведомость, повёрнутая на 90°: каждая колонка — одно помещение."""
    n = len(table)
    if n < 6:
        return
    items = []
    for j in range(len(table[0])):
        внутр = clean(table[1][j])
        if внутр and not re.search(r"внутр", внутр, re.I):
            items.append(j)
    items.reverse()   # при повороте порядок колонок обратный
    title = ""
    for row in table:
        for c in row:
            if c and re.search(r"этаж", c, re.I):
                title = clean(c)
    sums = _Sums(doc)
    for j in items:
        g = lambda r: clean(table[r][j]) if r < n else ""  # noqa: E731
        area_f, area_p = parse_area(g(4)), parse_area(g(3))
        sums.add(area_f, area_p)
        flags = []
        if g(3) and area_p is None:
            flags.append("площадь не число")
        doc.records.append({**base, "Этаж_документ": title, "Раздел": "",
                            "Номер_помещения": g(1), "Номер_правоуст": g(0),
                            "Назначение": g(2), "Площадь_м2": area_f, "Площадь_правоуст_м2": area_p,
                            "Категория": "", "Кол_чел": "", "Подразделение": g(5),
                            "Примечание": g(6), "Тип_экспликации": 1, "Проверить": ", ".join(flags)})
    tot_p, tot_f = (parse_area(table[3][0]), parse_area(table[4][0])) if n > 4 else (None, None)
    if tot_f is not None or tot_p is not None:
        sums.total("Итого (повёрнутая таблица)", tot_f, tot_p)


# ------------------------------------------------------------------ тип 2
_CODE_RE = re.compile(r"^-?\d+([./]\d+)*[а-яёa-z]?$", re.I)
_SUBTOTAL_RE = re.compile(r"^\d[\d\s]*[,.]\d+\s*м²")
_SECTION_RE = re.compile(r"(\d+)\.\s+([А-ЯЁA-Z].*)$")


def _parse_explication(table, doc: ParsedDoc, base: dict):
    hdr = next((i for i, r in enumerate(table) if r and "пом" in clean(r[0]).lower() and "№" in r[0]), None)
    if hdr is None:
        doc.notes.append("не найдена шапка таблицы")
        return
    title = clean(table[0][0]) if table and table[0] and table[0][0] else ""
    sums = _Sums(doc)
    section = ""
    for r in table[hdr + 1:]:
        r = [(c or "") for c in r] + [""] * 5
        c0, c1, c2, c3, c4 = r[:5]
        if _CODE_RE.match(clean(c0)):
            area = parse_area(c2)
            sums.add(area, None)
            flags = [] if area is not None else ["площадь не число"]
            doc.records.append({**base, "Этаж_документ": title, "Раздел": section,
                                "Номер_помещения": clean(c0), "Номер_правоуст": "",
                                "Назначение": clean(c1), "Площадь_м2": area, "Площадь_правоуст_м2": None,
                                "Категория": clean(c3), "Кол_чел": clean(c4), "Подразделение": "",
                                "Примечание": "", "Тип_экспликации": 2, "Проверить": ", ".join(flags)})
            continue
        if any(clean(x) for x in (c1, c2, c3, c4)):
            if clean(c1):   # строка с данными, но код не распознан — не теряем
                area = parse_area(c2)
                doc.records.append({**base, "Этаж_документ": title, "Раздел": section,
                                    "Номер_помещения": clean(c0), "Номер_правоуст": "",
                                    "Назначение": clean(c1), "Площадь_м2": area, "Площадь_правоуст_м2": None,
                                    "Категория": clean(c3), "Кол_чел": clean(c4), "Подразделение": "",
                                    "Примечание": "", "Тип_экспликации": 2, "Проверить": "код не распознан"})
                sums.add(area, None)
            continue
        for line in c0.split("\n"):
            line = clean(line)
            if not line:
                continue
            if line.lower().startswith("общий итог"):
                continue
            if _SUBTOTAL_RE.match(line):
                sums.total(f"подитог раздела «{section}»", parse_area(line.split("м²")[0] + "м²"), None)
                m = _SECTION_RE.search(line.split("м²", 1)[1]) if "м²" in line else None
                if m:
                    section = f"{m.group(1)}. {m.group(2)}"
                continue
            m = _SECTION_RE.search(line)
            section = f"{m.group(1)}. {m.group(2)}" if m else line


# ----------------------------------------------------------------- вход
def parse_pdf(path: str | Path, ref=None) -> ParsedDoc:
    path = Path(path)
    ctx = file_context(path)
    doc = ParsedDoc(file=path.name)
    b = ctx["building"]
    base = {"Здание_код": b, "Здание": "", "Этаж_код": floor_code(b, ctx),
            "Этаж_файл": ctx["floor_label"], "Лист": ctx["sheet"], "Наземный_подземный": "",
            "Файл": path.name, "Чтение": "текст"}
    if ref is not None and b:
        from core.reference import ground_state
        base["Здание"] = ref.building_name(b)
        base["Наземный_подземный"] = ground_state(ref, b, base["Этаж_код"])
    if not b:
        doc.notes.append("здание не определено по имени файла")
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        text = page.extract_text() or ""
        vector = len(page.chars) < 30
        if "Экспликация помещений" in text:
            doc.kind = 2
            tables = page.extract_tables()
            if tables:
                _parse_explication(max(tables, key=len), doc, base)
        else:
            doc.kind = 1
            if vector:
                doc.method, base["Чтение"] = "OCR", "OCR"
            big = None
            if not vector:
                tables = page.extract_tables()
                big = max(tables, key=lambda t: len(t) * len(t[0])) if tables else None
            # повёрнутая ведомость: в первой строке несколько номеров «ч.п.»
            if big and sum("ч.п" in (c or "") for c in big[0]) >= 3:
                doc.notes.append("таблица повёрнута, транспонирована")
                _parse_transposed(big, doc, base)
            else:
                mat, full, cont = grid_matrix(page, ocr=vector)
                if mat is None:
                    doc.notes.append("таблица не распознана")
                else:
                    _parse_ledger(mat, full, cont, doc, base, ocr=vector)
    for rec in doc.records:
        for k in FIELDS:
            rec.setdefault(k, "")
        if ref is not None:
            rec["Проверить"] = rec["Проверить"]
    return doc
