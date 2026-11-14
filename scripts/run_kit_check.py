"""Прогон одного комплекта из РД/ через цепочку ВОР -> СО -> ВОР+СО в Excel (отдельная БД, проект не меняется).

Работа разбита на стадии, каждая короче ~3 мин (таймаут 170 с), запускать по очереди:
  build            копия ВОР и СО комплекта в data/_pq_work/<метка>/docs, разбор, сборка трёх книг в books/
  refresh <1|2|3>  обновление одной книги в Excel: 1 - ВОР, 2 - СО, 3 - ВОР+СО (Excel пользователя закрыт)
  report           лист Ошибки обновлённой книги ВОР+СО (замечания «по наименованию»)

Запуск (из venv):  python -X utf8 -m scripts.run_kit_check <подстрока пути в РД/> <метка> <стадия> [номер книги]
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

STAGE_TIMEOUT = 170  # секунд на стадию


def build(key, work):
    from core import query_builder
    from find_dup_cases import is_so, is_vor
    from scripts.process_folder import process_folder

    src = next(p for p in sorted((ROOT / "РД").rglob("*")) if p.is_dir() and key in str(p) and
               any(f.suffix.lower() == ".docx" and is_vor(f.name) for f in p.iterdir()))
    if work.exists():
        shutil.rmtree(work)
    docs, out = work / "docs", work / "books"
    docs.mkdir(parents=True)
    out.mkdir()
    for f in src.iterdir():
        if f.suffix.lower() in (".doc", ".docx") and (is_vor(f.name) or is_so(f.name)) and not f.name.startswith("~$"):
            shutil.copy(f, docs / f.name)
            print("копия:", f.name)
    db = str(work / "x.db")
    rows = process_folder(str(docs), db_path=db, errors=[])
    ids = [r["file_id"] for r in rows if r["status"] == "SAVED" or r["csv_path"]]
    res = query_builder.build_queries(ids, db_path=db, out_dir=str(out), mode=query_builder.MODE_VOR_SO)
    print("книги:", [os.path.basename(b["path"]) for b in res["books"]], "пропущено:", len(res["skipped"]))


def books_of(work):
    files = sorted((work / "books").glob("*.xlsx"))
    order = {"ВОР+СО_": 3, "ВОР_": 1, "СО_": 2}
    return sorted(files, key=lambda p: next(v for k, v in order.items() if p.name.startswith(k)))


def refresh(work, n):
    book = books_of(work)[n - 1]
    print("обновляю:", book.name)
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(ROOT / "scripts" / "refresh_books.ps1"), "-Books", str(book),
                        "-TimeoutSec", str(STAGE_TIMEOUT - 10)], timeout=STAGE_TIMEOUT)
    sys.exit(r.returncode)


def report(work):
    book = books_of(work)[2]
    subprocess.run([sys.executable, "-I", "-X", "utf8", str(ROOT / "scripts" / "show_errors_sheet.py"), str(book)],
                   timeout=STAGE_TIMEOUT)


def main():
    key, label, stage = sys.argv[1], sys.argv[2], sys.argv[3]
    work = ROOT / "data" / "_pq_work" / label
    if stage == "build":
        build(key, work)
    elif stage == "refresh":
        refresh(work, int(sys.argv[4]))
    elif stage == "report":
        report(work)
    else:
        sys.exit("стадия: build | refresh N | report")


if __name__ == "__main__":
    main()
