# snapshot_save.py

# python snapshot_save.py workai_snapshot_before.xlsx Snapshot before.csv

import pandas as pd
import sys
from datetime import datetime

def save_snapshot(xlsx_path, sheet_name, out_csv):
    df = pd.read_excel(xlsx_path, sheet_name=sheet_name)
    df.to_csv(out_csv, index=False, encoding='utf-8-sig')
    print(f'[+] Снапшот сохранён: {out_csv}')
    print(f'    Строк: {len(df)}, колонок: {len(df.columns)}')
    print(f'    Колонки: {list(df.columns)}')

if __name__ == '__main__':
    # Пример запуска:
    #   python snapshot_save.py workai_snapshot_before.xlsx Snapshot before.csv
    save_snapshot(sys.argv[1], sys.argv[2], sys.argv[3])