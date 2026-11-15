import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rooms_to_excel", ROOT / "scripts" / "rooms_to_excel.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _rec(num, area, note=""):
    return {"Номер_помещения": num, "Номер_правоуст": "1-Н", "Назначение": "Щитовая",
            "Площадь_м2": area, "Площадь_правоуст_м2": area, "Подразделение": "Э", "Примечание": note}


def test_compare_manual_finds_differences(tmp_path):
    csv_path = tmp_path / "a.pdf.csv"
    csv_path.write_text(
        '"№";"№ внутр.";"Назн";"Пл прав";"Пл факт";"Подр";"Прим"\n'
        '"1-Н";"1";"Щитовая";"7;6";"7;6";"Э";""\n'
        '"1-Н";"2";"Щитовая";"8;0";"8;0";"Э";""\n'
        '"1-Н";"3";"Щитовая";"9;0";"9;0";"Э";""\n', encoding="utf-8")
    data = {"file": "a.pdf", "records": [_rec("1", 7.6), _rec("2", 8.5), _rec("4", 1.0)]}
    diffs = mod.compare_manual(data, csv_path)
    got = {(d["Номер"], d["Поле"]) for d in diffs}
    assert ("2", "Площадь_м2") in got and ("2", "Площадь_правоуст_м2") in got
    assert ("3", "помещение") in got and ("4", "помещение") in got
    assert not any(n == "1" for n, _ in got)


def test_write_xlsx_sheets(tmp_path):
    import openpyxl
    d = {"file": "a.pdf", "folder": "Тип 1", "kind": 1, "method": "текст", "records": [_rec("1", 7.6)],
         "checks": [{"Итого": "Итого", "Совпало": "да", "Детали": ""}], "notes": []}
    out = tmp_path / "x.xlsx"
    mod.write_xlsx([d], [], out)
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Помещения", "Проверка", "Файлы"]
    assert wb["Помещения"].max_row == 2
