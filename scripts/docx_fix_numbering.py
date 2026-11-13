# docx_fix_numbering.py
import os
import sys
import re
import argparse
import zipfile
import shutil
import tempfile
from lxml import etree
from docx import Document

NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
}


def qn(tag):
    """Префикс для пространства имён Word (для set/get атрибутов)."""
    return f'{{{NS["w"]}}}{tag}'


# ============================================================
# 1. ПАРСИНГ numbering.xml (работаем на lxml → namespaces=NS нужен)
# ============================================================
def parse_numbering(numbering_xml_path):
    """
    Возвращает словарь:
    num_id -> {
        'levels': {
            ilvl: {
                'start': int,
                'startOverride': int | None,
                'numFmt': str,
                'lvlText': str
            }
        }
    }
    """
    tree = etree.parse(numbering_xml_path)
    root = tree.getroot()

    # 1.1 Абстрактные определения
    abstract_styles = {}
    for abstract_num in root.xpath('//w:abstractNum', namespaces=NS):
        abstract_id = abstract_num.get(qn('abstractNumId'))
        levels = {}
        for lvl in abstract_num.xpath('.//w:lvl', namespaces=NS):
            ilvl = lvl.get(qn('ilvl'))

            start_el = lvl.xpath('./w:start', namespaces=NS)
            start = int(start_el[0].get(qn('val'))) if start_el else 1

            fmt_el = lvl.xpath('./w:numFmt', namespaces=NS)
            num_fmt = fmt_el[0].get(qn('val')) if fmt_el else 'decimal'

            text_el = lvl.xpath('./w:lvlText', namespaces=NS)
            lvl_text = text_el[0].get(qn('val')) if text_el else '%1.'

            levels[ilvl] = {
                'start': start,
                'startOverride': None,
                'numFmt': num_fmt,
                'lvlText': lvl_text
            }
        abstract_styles[abstract_id] = levels

    # 1.2 Конкретные numId + override'ы
    num_map = {}
    for num in root.xpath('//w:num', namespaces=NS):
        num_id = num.get(qn('numId'))
        abstract_id_el = num.xpath('./w:abstractNumId', namespaces=NS)
        if not abstract_id_el:
            continue
        abstract_id = abstract_id_el[0].get(qn('val'))

        levels = {}
        for ilvl, lvl_data in abstract_styles.get(abstract_id, {}).items():
            levels[ilvl] = lvl_data.copy()

        for override in num.xpath('./w:lvlOverride', namespaces=NS):
            ilvl = override.get(qn('ilvl'))
            start_override_el = override.xpath('./w:startOverride', namespaces=NS)
            if start_override_el and ilvl in levels:
                levels[ilvl]['startOverride'] = int(start_override_el[0].get(qn('val')))

        num_map[num_id] = {'levels': levels, 'abstract': abstract_id}

    return num_map


def parse_style_numbering(styles_bytes):
    """
    Нумерация, заданная в стилях абзацев (styles.xml).
    Возвращает {styleId: (numId | None, ilvl | None)} с учётом наследования
    через w:basedOn (свои значения стиля важнее унаследованных).
    """
    root = etree.fromstring(styles_bytes)
    raw = {}
    for style in root.xpath('//w:style[@w:type="paragraph"]', namespaces=NS):
        style_id = style.get(qn('styleId'))
        based = style.xpath('./w:basedOn', namespaces=NS)
        num_id_el = style.xpath('./w:pPr/w:numPr/w:numId', namespaces=NS)
        ilvl_el = style.xpath('./w:pPr/w:numPr/w:ilvl', namespaces=NS)
        raw[style_id] = (
            based[0].get(qn('val')) if based else None,
            num_id_el[0].get(qn('val')) if num_id_el else None,
            ilvl_el[0].get(qn('val')) if ilvl_el else None,
        )

    resolved = {}
    for style_id in raw:
        num_id = ilvl = None
        seen = set()
        current = style_id
        while current in raw and current not in seen:
            seen.add(current)
            parent, own_num, own_ilvl = raw[current]
            if num_id is None and own_num is not None:
                num_id = own_num
            if ilvl is None and own_ilvl is not None:
                ilvl = own_ilvl
            current = parent
        if num_id is not None or ilvl is not None:
            resolved[style_id] = (num_id, ilvl)
    return resolved


# ============================================================
# 2. ФОРМАТИРОВАНИЕ НОМЕРА
# ============================================================
def format_number(num_fmt, value):
    """Примитивное форматирование. Для decimal возвращает строку числа."""
    if num_fmt in ('decimal', 'decimalZero'):
        return str(value)
    return str(value)


# ============================================================
# 3. ОБРАБОТКА ОДНОГО ФАЙЛА
# ============================================================
def process_file(input_path, output_path, verbose=True):
    """
    Обрабатывает один docx:
      1) распаковывает для чтения numbering.xml,
      2) открывает документ ОДИН раз,
      3) считает номера и тут же правит дерево,
      4) сохраняет.
    """
    # --- 1. Распаковка ради word/numbering.xml ---
    with zipfile.ZipFile(input_path, 'r') as z:
        if 'word/numbering.xml' not in z.namelist():
            if verbose:
                print(f'[!] В файле {input_path} нет numbering.xml — пропускаем.')
            return None
        numbering_bytes = z.read('word/numbering.xml')
        styles_bytes = z.read('word/styles.xml') if 'word/styles.xml' in z.namelist() else None

    temp_dir = tempfile.mkdtemp(prefix='docx_num_')
    try:
        numbering_path = os.path.join(temp_dir, 'numbering.xml')
        with open(numbering_path, 'wb') as fh:
            fh.write(numbering_bytes)
        num_map = parse_numbering(numbering_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # --- 2. Один экземпляр Document ---
    doc = Document(input_path)
    body = doc.element.body

    counters = {}
    seen_nums = set()
    modified = 0
    skipped_no_def = 0

    # Собираем параграфы в список заранее — мы будем менять их содержимое
    paragraphs = body.xpath('.//w:p')

    style_numbering = parse_style_numbering(styles_bytes) if styles_bytes else {}

    for p in paragraphs:
        num_pr_list = p.xpath('./w:pPr/w:numPr')
        num_id = ilvl = None
        if num_pr_list:
            num_id_el = num_pr_list[0].xpath('./w:numId')
            ilvl_el = num_pr_list[0].xpath('./w:ilvl')
            num_id = num_id_el[0].get(qn('val')) if num_id_el else None
            ilvl = ilvl_el[0].get(qn('val')) if ilvl_el else None

        # Нумерация из стиля абзаца: прямой numPr важнее, numId=0 отключает номер
        from_style = False
        if num_id is None:
            style_el = p.xpath('./w:pPr/w:pStyle')
            style_id = style_el[0].get(qn('val')) if style_el else None
            if style_id in style_numbering:
                style_num, style_ilvl = style_numbering[style_id]
                if style_num is not None:
                    num_id = style_num
                    ilvl = ilvl if ilvl is not None else style_ilvl
                    from_style = True
        if num_id is None:
            continue
        if ilvl is None:
            ilvl = '0'

        if num_id not in num_map or ilvl not in num_map[num_id]['levels']:
            skipped_no_def += 1
            continue

        level_def = num_map[num_id]['levels'][ilvl]
        if from_style and level_def['numFmt'] == 'bullet':
            continue  # маркер списка, не номер
        # Как в Word: разные numId с одним abstractNum делят счётчики;
        # перезапуск только при первом использовании numId с startOverride.
        group = num_map[num_id].get('abstract', num_id)
        if num_id not in seen_nums:
            seen_nums.add(num_id)
            for lvl_key, lvl_def_o in num_map[num_id]['levels'].items():
                if lvl_def_o['startOverride'] is not None:
                    counters.pop((group, lvl_key), None)
        key = (group, ilvl)

        if key not in counters:
            initial = (level_def['startOverride']
                       if level_def['startOverride'] is not None
                       else level_def['start'])
            counters[key] = initial
        else:
            counters[key] += 1

        current_val = counters[key]

        # Как в Word: пропущенные старшие уровни считаются уже начатыми (1.1 без «1.»),
        # поэтому следующий абзац старшего уровня получит следующий номер, а не 1
        for j in range(int(ilvl)):
            upper_key = (group, str(j))
            if upper_key not in counters:
                upper_def = num_map[num_id]['levels'].get(str(j))
                if upper_def is not None:
                    counters[upper_key] = (upper_def['startOverride']
                                           if upper_def['startOverride'] is not None
                                           else upper_def['start'])

        # Сброс счётчиков более глубоких уровней
        # (по умолчанию в Word: при инкременте уровня k все уровни > k сбрасываются)
        for k in list(counters.keys()):
            if k[0] == group and int(k[1]) > int(ilvl):
                del counters[k]

        # Подстановка ВСЕХ плейсхолдеров %N в lvlText
        def _replace_placeholder(match):
            level_num = int(match.group(1)) - 1  # %1 → уровень 0, %2 → уровень 1, ...
            level_key = (group, str(level_num))
            if level_key in counters:
                val = counters[level_key]
            else:
                lvl_def_ph = num_map[num_id]['levels'].get(str(level_num))
                if lvl_def_ph is None:
                    return match.group(0)
                val = (lvl_def_ph['startOverride']
                       if lvl_def_ph['startOverride'] is not None
                       else lvl_def_ph['start'])
            lvl_def_ph = num_map[num_id]['levels'].get(str(level_num))
            fmt = lvl_def_ph['numFmt'] if lvl_def_ph else 'decimal'
            return format_number(fmt, val)

        label_text = re.sub(r'%(\d)', _replace_placeholder, level_def['lvlText'])
        label_text = label_text.strip(' .,;:)]}>')

        # --- 3. Правим ТО ЖЕ дерево ---
        # 3.1 Убираем автонумерацию
        for np in num_pr_list:
            np.getparent().remove(np)

        # Скрытый абзац (знак абзаца с w:vanish): номер учтён в счётчике,
        # но в Word он не виден, поэтому в текст его не вставляем
        if p.xpath('./w:pPr/w:rPr/w:vanish[not(@w:val="0") and not(@w:val="false")]'):
            continue

        # 3.2 Явно обнуляем отступ (перебивает стиль pStyle)
        p_pr_list = p.xpath('./w:pPr')
        if p_pr_list:
            p_pr = p_pr_list[0]
            # Удаляем существующий w:ind
            for ind in p_pr.xpath('./w:ind'):
                p_pr.remove(ind)
            # Добавляем явный нулевой w:ind — это override для стиля
            ind_el = etree.Element(qn('ind'))
            ind_el.set(qn('left'), '0')
            ind_el.set(qn('start'), '0')
            ind_el.set(qn('firstLine'), '0')
            ind_el.set(qn('hanging'), '0')
            # Вставляем в правильную позицию по схеме OOXML
            # (перед w:jc / w:outlineLvl / w:rPr и т.п., если они есть)
            after_tags = ['contextualSpacing', 'mirrorIndents', 'suppressOverlap',
                          'jc', 'textDirection', 'textAlignment', 'textboxTightWrap',
                          'outlineLvl', 'divId', 'cnfStyle', 'rPr', 'sectPr', 'pPrChange']
            inserted = False
            for tag in after_tags:
                found = p_pr.xpath(f'./w:{tag}')
                if found:
                    found[0].addprevious(ind_el)
                    inserted = True
                    break
            if not inserted:
                p_pr.append(ind_el)

        # 3.3 Вставляем номер как обычный текст
        new_run = etree.SubElement(p, qn('r'))
        t = etree.SubElement(new_run, qn('t'))
        t.text = label_text + ' '

        if p_pr_list:
            p_pr_list[0].addnext(new_run)
        else:
            p.insert(0, new_run)

        modified += 1

    # --- 4. Сохраняем ---
    doc.save(output_path)

    if verbose:
        print(f'[+] Готово: {output_path} '
              f'(изменено параграфов: {modified}, пропущено без определения: {skipped_no_def})')

    if modified == 0 and verbose:
        print('[!] ВНИМАНИЕ: ни один параграф с numPr не найден.')
        print('    Возможно, нумерация задана через стиль (w:pStyle → styles.xml),')
        print('    а не напрямую в параграфе.')

    return modified


# ============================================================
# 4. ЧТЕНИЕ СПИСКА ФАЙЛОВ (BOM-устойчиво)
# ============================================================
def read_file_list(list_path):
    """
    Читает list.txt: один путь на строку.
    Поддерживает BOM (UTF-8 with BOM) и комментарии (#).
    Относительные пути разрешаются относительно папки, где лежит list.txt.
    """
    base_dir = os.path.dirname(os.path.abspath(list_path))
    files = []
    with open(list_path, 'r', encoding='utf-8-sig') as f:
        for raw in f:
            line = raw.strip().lstrip('\ufeff')
            if not line or line.startswith('#'):
                continue
            if not os.path.isabs(line):
                line = os.path.join(base_dir, line)
            files.append(line)
    return files


def collect_from_directory(dir_path):
    """Возвращает все .docx в директории (без рекурсии, без ~$ файлов)."""
    result = []
    for fname in os.listdir(dir_path):
        if fname.lower().endswith('.docx') and not fname.startswith('~$'):
            result.append(os.path.join(dir_path, fname))
    return result


# ============================================================
# 5. ТОЧКА ВХОДА
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description='Преобразование автонумерации Word в текст.',
        epilog='Примеры:\n'
               '  python docx_fix_numbering.py --dir "C:\\Docs"\n'
               '  python docx_fix_numbering.py --dir "C:\\Docs" --in-place\n'
               '  python docx_fix_numbering.py --list list.txt --in-place',
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dir', '-d', metavar='PATH',
                       help='Директория с .docx файлами (без рекурсии).')
    group.add_argument('--list', '-l', metavar='FILE',
                       help='Текстовый файл со списком .docx (один путь на строку).')
    parser.add_argument('--in-place', '-i', action='store_true',
                        help='Заменять исходные файлы (без создания _fixed копий). '
                             'Оригиналы предварительно резервируются в *.bak рядом с файлом.')
    args = parser.parse_args()

    if args.dir:
        if not os.path.isdir(args.dir):
            print(f'[!] Не директория: {args.dir}')
            sys.exit(1)
        files = collect_from_directory(args.dir)
    else:
        if not os.path.isfile(args.list):
            print(f'[!] Не файл: {args.list}')
            sys.exit(1)
        files = read_file_list(args.list)

    if not files:
        print('[!] Не найдено ни одного .docx. Проверьте источник.')
        sys.exit(1)

    print(f'[i] Обрабатываю {len(files)} файл(ов).')

    ok = 0
    failed = 0
    for f in files:
        if not f.lower().endswith('.docx'):
            print(f'[!] Пропуск (не .docx): {f}')
            failed += 1
            continue
        if not os.path.isfile(f):
            print(f'[!] Не найден: {f}')
            failed += 1
            continue

        # Куда сохраняем: либо во временный файл (при --in-place),
        # либо рядом как <имя>_fixed.docx
        if args.in_place:
            out = f + '.tmp'
        else:
            base, ext = os.path.splitext(f)
            out = base + '_fixed' + ext

        try:
            process_file(f, out)

            if args.in_place and os.path.exists(out):
                # Резервная копия только если её ещё нет
                backup = f + '.bak'
                if not os.path.exists(backup):
                    shutil.copy2(f, backup)
                # Атомарная замена оригинала
                os.replace(out, f)

            ok += 1
        except Exception as e:
            print(f'[!] Ошибка при обработке {f}: {e}')
            failed += 1
            # Убираем временный файл, чтобы не засорять папку
            if args.in_place and os.path.exists(out):
                try:
                    os.remove(out)
                except OSError:
                    pass

    print(f'[i] Готово. Успешно: {ok}, ошибок: {failed}.')
    sys.exit(0 if failed == 0 else 2)


if __name__ == '__main__':
    main()