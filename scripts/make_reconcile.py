"""Одна команда: отчёт сверки итогов комплекта ВОР / СО / ВОР+СО в Excel.

Запуск (venv, -I -X utf8):
  python scripts/make_reconcile.py [папка=data/queries] [метка времени, напр. 20261115_020507]
Без метки берётся последний комплект, где есть все три книги (ВОР_, СО_, ВОР+СО_).
Книги копируются во временную папку, Excel может быть открыт (если файл не занят эксклюзивно).
Результат: <папка>/Сверка_итогов_<метка>.xlsx
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

here = Path(__file__).resolve().parent
folder = Path(sys.argv[1] if len(sys.argv) > 1 else "data/queries")
stamp = sys.argv[2] if len(sys.argv) > 2 else None

if stamp is None:
    sets = {}
    for p in folder.glob("*.xlsx"):
        m = re.fullmatch(r"(ВОР\+СО|ВОР|СО)_(\d{8}_\d{6})\.xlsx", p.name)
        if m:
            sets.setdefault(m.group(2), set()).add(m.group(1))
    full = sorted(s for s, k in sets.items() if k == {"ВОР", "СО", "ВОР+СО"})
    if not full:
        sys.exit(f"В {folder} нет комплекта из трёх книг ВОР_/СО_/ВОР+СО_ с общим временем")
    stamp = full[-1]

src = {k: folder / f"{k}_{stamp}.xlsx" for k in ("ВОР", "СО", "ВОР+СО")}
for p in src.values():
    if not p.exists():
        sys.exit(f"Нет файла {p}")

out = folder / f"Сверка_итогов_{stamp}.xlsx"
py = [sys.executable, "-I", "-X", "utf8"]
with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    for k, name in (("ВОР", "v"), ("СО", "s"), ("ВОР+СО", "c")):
        try:
            shutil.copy2(src[k], t / f"{name}.xlsx")
        except PermissionError:
            sys.exit(f"Файл {src[k].name} занят (закройте его в Excel)")
    tsv = t / "reconcile.tsv"
    for cmd in (py + [str(here / "reconcile_totals.py"), str(t), str(tsv)],
                py + [str(here / "reconcile_to_xlsx.py"), str(tsv), str(out), stamp, "auto"]):
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if r.returncode:
            sys.exit(f"Ошибка {Path(cmd[4]).name}:\n{r.stderr[-1500:]}")
        for line in r.stdout.splitlines():
            if line.startswith(("ВНИМАНИЕ", "НЕТ в")):
                print(line)
print("saved", out)
