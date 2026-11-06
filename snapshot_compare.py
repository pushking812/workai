# snapshot_compare.py

# python snapshot_compare.py before.csv after.csv

import pandas as pd
import sys

def compare(before_csv, after_csv):
    df_b = pd.read_csv(before_csv, dtype=str, keep_default_na=False)
    df_a = pd.read_csv(after_csv, dtype=str, keep_default_na=False)

    print(f'Строк: было {len(df_b)}, стало {len(df_a)}', end='')
    if len(df_b) == len(df_a):
        print(' ✓')
    else:
        print(f' ❌ (разница {len(df_a) - len(df_b):+d})')

    if list(df_b.columns) != list(df_a.columns):
        print(f'❌ Набор колонок изменился!')
        only_b = set(df_b.columns) - set(df_a.columns)
        only_a = set(df_a.columns) - set(df_b.columns)
        if only_b: print(f'   Только в before: {only_b}')
        if only_a: print(f'   Только в after:  {only_a}')
    else:
        print(f'Колонок: {len(df_b.columns)} ✓')

    # Сравнение ячеек (только для пересечения колонок и строк)
    common_cols = [c for c in df_b.columns if c in df_a.columns]
    common_rows = min(len(df_b), len(df_a))
    diffs = []
    for r in range(common_rows):
        for c in common_cols:
            v_b = str(df_b.iloc[r][c])
            v_a = str(df_a.iloc[r][c])
            if v_b != v_a:
                diffs.append((r + 2, c, v_b, v_a))  # +2: Excel-строка (1 — заголовок, 1 — 1-я)

    if not diffs:
        print(f'\n✅ Расхождений нет — ячейки до {common_rows} строк совпадают попарно.')
    else:
        print(f'\n❌ Найдено {len(diffs)} расхождений (показаны первые 30):')
        print(f'{"Excel строка":>13} | {"Колонка":<25} | {"before":<40} | {"after":<40}')
        print('-' * 130)
        for row, col, vb, va in diffs[:30]:
            print(f'{row:>13} | {col:<25} | {vb[:40]:<40} | {va[:40]:<40}')
        if len(diffs) > 30:
            print(f'... и ещё {len(diffs) - 30}')
        sys.exit(2)

if __name__ == '__main__':
    compare(sys.argv[1], sys.argv[2])