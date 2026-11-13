"use strict";

const POLL_MS = 700;
const STATUS_LABELS = {
  FOUND: "Новый", VARIANTS: "Вариант", SAVED: "Не обработан", SAVED_CSV: "Сохранён",
  PROCESSING: "Обработка", NEEDS_MAPPING: "Нужен маппинг", READY: "Готово", ERROR: "Ошибка",
  HIDDEN: "Скрытый",
};
const STATUS_HINTS = {
  FOUND: "Найден при поиске, в базе появился впервые",
  VARIANTS: "Тот же шифр, изм. и дата, но другое содержимое",
  SAVED: "Записан в базу, таблицы ещё не выгружены в CSV",
  SAVED_CSV: "Таблицы выгружены в CSV",
  HIDDEN: "Скрыт из списка",
};

const state = {
  rows: [],
  selected: new Set(),
  sort: { key: "doc_code", dir: 1 },
  filter: "",
  searching: false,
  tasksRunning: false,
  stoppedByUser: false,
  hiddenMode: false,
  timer: null,
  root: "",
  kits: [],
  subfolders: [],
  knownTypes: ["ВОР", "СВОР", "СО", "КЖ"],
  hideUnknown: false,
  typeAliases: {},
  searchByType: false,
  interval: 60,
  bgTimer: null,
  expanded: new Set(),
};

// Папки поиска = выбранные комплекты внутри корневой папки.
function searchDirs() {
  if (!state.root) return [];
  const sep = state.root.includes("\\") ? "\\" : "/";
  const base = state.root.replace(/[\\/]+$/, "");
  return state.kits.map((name) => base + sep + name);
}

const $ = (id) => document.getElementById(id);
const el = {
  body: $("grid-body"), empty: $("empty"), status: $("status-text"), progress: $("progress"),
  search: $("btn-search"), stop: $("btn-stop"), add: $("btn-add"), save: $("btn-save"),
  queries: $("btn-queries"),
  hide: $("btn-hide"), showHidden: $("btn-show-hidden"), exit: $("btn-exit"),
  settings: $("btn-settings"), filter: $("input-filter"),
  selectAll: $("btn-select-all"), chkAll: $("chk-all"), count: $("selected-count"),
  background: $("chk-background"),
};

function api() {
  return window.pywebview.api;
}

// Состояние основного окна (сортировка, фильтр, раскрытые группы) хранится в конфиге.
let uiTimer = null;
function saveUi() {
  clearTimeout(uiTimer);
  uiTimer = setTimeout(() => {
    try {
      api().save_settings({
        ui: {
          sort: state.sort,
          filter: state.filter,
          expanded: [...state.expanded],
        },
      });
    } catch (e) { /* состояние окна не критично */ }
  }, 400);
}

function applyUi(ui) {
  if (!ui) return;
  if (ui.sort) state.sort = ui.sort;
  if (typeof ui.filter === "string") {
    state.filter = ui.filter;
    el.filter.value = ui.filter;
  }
  if (Array.isArray(ui.expanded)) state.expanded = new Set(ui.expanded);
}

// ---------- Данные ----------

function dirName(path) {
  return String(path ?? "").replace(/[\\/][^\\/]*$/, "");
}

function effectiveStatus(row, hit) {
  if (row.status === "HIDDEN") return "HIDDEN";
  if (row.status === "SAVED") {
    if (row.csv_path) return "SAVED_CSV";
    if (hit && (hit.ui_status === "FOUND" || hit.ui_status === "VARIANTS")) return hit.ui_status;
  }
  return row.status;
}

function mergeRows(data) {
  const found = new Map();
  for (const item of data.found || []) {
    if (item.file_id != null) found.set(item.file_id, item);
  }
  const rows = (data.files || []).map((row) => ({
    ...row,
    db_status: row.status,
    status: effectiveStatus(row, found.get(row.id)),
    dir: dirName(row.path),
  }));
  const groups = new Map();
  for (const row of rows) {
    if (!row.doc_code) continue;
    const key = [row.doc_code, row.revision, row.revision_date].join("|");
    if (!groups.has(key)) groups.set(key, new Set());
    groups.get(key).add(row.hash);
  }
  for (const row of rows) {
    const key = [row.doc_code, row.revision, row.revision_date].join("|");
    row.is_variant = !!row.doc_code && groups.get(key).size > 1;
  }
  return rows;
}

async function refresh() {
  const data = await api().get_files();
  state.rows = mergeRows(data);
  const ids = new Set(state.rows.map((r) => r.id));
  for (const id of [...state.selected]) if (!ids.has(id)) state.selected.delete(id);
  if (state.hiddenMode && !state.rows.some((r) => r.db_status === "HIDDEN")) leaveHiddenMode();
  render();
}

// ---------- Отрисовка ----------

function formatSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return bytes + " Б";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " КБ";
  return (bytes / 1024 / 1024).toFixed(1) + " МБ";
}

function formatTime(seconds) {
  return seconds == null ? "" : new Date(seconds * 1000).toLocaleString("ru-RU");
}

const LOOKALIKES = {
  A: "А", B: "В", C: "С", E: "Е", H: "Н", K: "К", M: "М", O: "О", P: "Р", T: "Т", X: "Х", Y: "У",
  a: "а", b: "в", c: "с", e: "е", h: "н", k: "к", m: "м", o: "о", p: "р", t: "т", x: "х", y: "у",
};
function normText(s) {
  return String(s ?? "").replace(/[A-Za-z]/g, (ch) => LOOKALIKES[ch] || ch).toLowerCase();
}

function visibleRows() {
  const needle = normText(state.filter.trim());
  let rows = state.rows.filter((r) => (r.db_status === "HIDDEN") === state.hiddenMode);
  if (state.hideUnknown) rows = rows.filter((r) => state.knownTypes.includes(r.doc_type));
  if (needle) {
    rows = rows.filter((r) =>
      [r.doc_code, r.revision, r.revision_date, r.filename, r.path, STATUS_LABELS[r.status]]
        .some((v) => normText(v).includes(needle)));
  }
  const key = state.sort.key === "path" ? "dir" : state.sort.key;
  const dir = state.sort.dir;
  rows.sort((a, b) => {
    const x = a[key] ?? "", y = b[key] ?? "";
    const cmp = typeof x === "number" && typeof y === "number"
      ? x - y
      : String(x).localeCompare(String(y), "ru", { numeric: true });
    return cmp * dir || a.id - b.id;
  });
  return rows;
}

function cell(text, className) {
  const td = document.createElement("td");
  const value = text == null ? "" : String(text);
  td.textContent = value;
  td.title = value;
  if (className) td.className = className;
  return td;
}

function badge(row) {
  const span = document.createElement("span");
  const label = STATUS_LABELS[row.status] || row.status;
  span.className = "badge " + row.status;
  span.textContent = label;
  span.title = STATUS_HINTS[row.status] || label;
  if (row.status === "ERROR") {
    span.title = "Ошибка: нажмите, чтобы увидеть текст";
    span.addEventListener("click", (e) => {
      e.stopPropagation();
      showError(row.error_message || "Текст ошибки не сохранён");
    });
  }
  return span;
}

// Дерево «по комплекту»: Шифр -> Номер изменения -> Дата (узла типа документа нет).
function shortDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? `${m[3]}.${m[2]}.${m[1].slice(2)}` : (iso || "без даты");
}

function buildKitTree(rows) {
  const codes = new Map();
  for (const row of rows) {
    const code = row.kit_code || "Без шифра";
    const rev = row.kit_revision ?? 0;
    const date = row.kit_date || "";
    if (!codes.has(code)) codes.set(code, new Map());
    const revs = codes.get(code);
    if (!revs.has(rev)) revs.set(rev, new Map());
    const dates = revs.get(rev);
    if (!dates.has(date)) dates.set(date, []);
    dates.get(date).push(row);
  }
  const byName = (x, y) => String(x[0]).localeCompare(String(y[0]), "ru", { numeric: true });
  return [...codes].sort(byName).map(([code, revs]) => ({
    name: code, key: "kit:c:" + code,
    revisions: [...revs].sort(byName).map(([rev, dates]) => ({
      name: `Изм.${rev}`, key: `kit:r:${code}|${rev}`,
      dates: [...dates].sort(byName).map(([date, files]) => ({
        name: `от ${shortDate(date)}`, key: `kit:d:${code}|${rev}|${date}`, files,
      })),
    })),
  }));
}

function renderKitTree(rows) {
  for (const code of buildKitTree(rows)) {
    const codeFiles = code.revisions.flatMap((r) => r.dates.flatMap((d) => d.files));
    const head = groupRow(code.name, code.key, 1, codeFiles);
    el.body.appendChild(head.tr);
    if (!head.open) continue;
    for (const rev of code.revisions) {
      const revHead = groupRow(rev.name, rev.key, 2, rev.dates.flatMap((d) => d.files));
      el.body.appendChild(revHead.tr);
      if (!revHead.open) continue;
      for (const date of rev.dates) {
        const dateHead = groupRow(date.name, date.key, 3, date.files);
        el.body.appendChild(dateHead.tr);
        if (!dateHead.open) continue;
        for (const row of date.files) el.body.appendChild(fileRow(row));
      }
    }
  }
}

function groupRow(label, key, level, files) {
  const open = state.filter.trim() !== "" || state.expanded.has(key);
  const chosen = files.filter((r) => state.selected.has(r.id)).length;

  const tr = document.createElement("tr");
  tr.className = "group level-" + level;

  const check = document.createElement("td");
  check.className = "col-check";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = files.length > 0 && chosen === files.length;
  box.indeterminate = chosen > 0 && chosen < files.length;
  box.addEventListener("click", (e) => e.stopPropagation());
  box.addEventListener("change", () => {
    for (const r of files) {
      if (box.checked) state.selected.add(r.id); else state.selected.delete(r.id);
    }
    render();
  });
  check.appendChild(box);
  tr.appendChild(check);

  const td = document.createElement("td");
  td.colSpan = 8;
  td.textContent = `${open ? "▼" : "▶"} ${label}  (${files.length})`;
  td.title = td.textContent;
  tr.appendChild(td);
  tr.addEventListener("click", () => {
    if (state.expanded.has(key)) state.expanded.delete(key); else state.expanded.add(key);
    saveUi();
    render();
  });
  return { tr, open };
}

// Ширина столбцов Статус, Размер, Дата файла — по самому длинному значению (и заголовку).
const FIT_COLUMNS = [["c-status", 22], ["c-size", 0], ["c-mtime", 0]];
let measureCtx = null;

function fitColumns() {
  if (!measureCtx) measureCtx = document.createElement("canvas").getContext("2d");
  const probe = document.querySelector("#grid-body td") || document.querySelector("#grid thead th");
  measureCtx.font = getComputedStyle(probe).font;
  const rows = [...el.body.querySelectorAll("tr:not(.group)")];
  const head = [...document.querySelectorAll("#grid thead th")];
  for (const [cls, extra] of FIT_COLUMNS) {
    const col = document.querySelector("col." + cls);
    const index = [...col.parentNode.children].indexOf(col);
    let widest = measureCtx.measureText(head[index].textContent).width + 18;  // + стрелка сортировки
    for (const tr of rows) {
      const td = tr.children[index];
      if (td) widest = Math.max(widest, measureCtx.measureText(td.textContent).width + extra);
    }
    col.style.width = Math.ceil(widest + 14) + "px";  // + отступы ячейки
  }
}

// Свернуть/развернуть всё дерево: если что-то раскрыто, сворачиваем, иначе раскрываем все узлы.
function toggleTree() {
  const keys = [];
  for (const c of buildKitTree(visibleRows())) {
    keys.push(c.key);
    for (const r of c.revisions) {
      keys.push(r.key);
      for (const d of r.dates) keys.push(d.key);
    }
  }
  if (keys.some((k) => state.expanded.has(k))) {
    for (const k of keys) state.expanded.delete(k);
  } else {
    for (const k of keys) state.expanded.add(k);
  }
  saveUi();
  render();
}

function render() {
  const rows = visibleRows();
  const tb = document.getElementById("btn-toggle-tree");
  if (tb) {
    const any = [...state.expanded].some((k) => k.startsWith("kit:"));
    tb.title = any ? "Свернуть дерево" : "Развернуть дерево";
  }
  el.body.replaceChildren();
  renderKitTree(rows);
  fitColumns();
  el.empty.hidden = rows.length > 0;
  el.empty.textContent = state.hiddenMode
    ? "Скрытых файлов нет."
    : "Файлов пока нет. Нажмите «Поиск» или «Добавить файл».";
  for (const th of document.querySelectorAll("th[data-sort]")) {
    th.classList.toggle("sorted-asc", th.dataset.sort === state.sort.key && state.sort.dir === 1);
    th.classList.toggle("sorted-desc", th.dataset.sort === state.sort.key && state.sort.dir === -1);
  }
  updateControls();
}

function fileRow(row) {
  const tr = document.createElement("tr");
  if (row.db_status === "HIDDEN") tr.classList.add("hidden-file");
  if (row.is_variant) tr.classList.add("variant");
  if (state.selected.has(row.id)) tr.classList.add("selected");

  const check = document.createElement("td");
  check.className = "col-check";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = state.selected.has(row.id);
  box.addEventListener("change", () => toggle(row.id, box.checked));
  check.appendChild(box);
  tr.appendChild(check);

  const codeCell = cell(row.doc_code, "doc_code");
  if (row.kit_problem || row.kit_forced) {
    // Проблема с файлом: штамп не сходится с папкой комплекта (или принят в комплект вручную).
    tr.classList.add("kit-problem");
    codeCell.textContent = (row.doc_code || "") + " ⓘ";
    codeCell.title = "Проблема с файлом: " + (row.kit_problem || "принят в комплект вручную");
  }
  tr.appendChild(codeCell);
  tr.appendChild(cell(row.revision, "revision"));
  const dateCell = cell(row.revision_date, "revision_date");
  if (row.revision_date && row.revision_date_source === "filename") {
    // дата взята из имени файла (новее даты штампа): пользователь должен это видеть
    dateCell.textContent = row.revision_date + " ⓘ";
    dateCell.title = "Дата взята из имени файла (она новее даты в штампе)";
  } else if (row.revision_date && row.revision_date_source === "modified") {
    dateCell.textContent = row.revision_date + " ⓘ";
    dateCell.title = "Даты нет ни в штампе, ни в имени: взята дата изменения файла";
  }
  tr.appendChild(dateCell);
  tr.appendChild(cell(row.filename, "filename"));
  tr.appendChild(cell(row.dir, "path"));
  const status = document.createElement("td");
  status.appendChild(badge(row));
  tr.appendChild(status);
  tr.appendChild(cell(formatSize(row.size), "size"));
  tr.appendChild(cell(formatTime(row.file_mtime), "file_mtime"));
  // Временное решение: двойной щелчок по сохранённому файлу открывает его CSV.
  // Только по ячейке статуса: двойной щелчок по тексту выделяет слово, а не открывает файл.
  status.addEventListener("dblclick", () => openCsv(row));
  return tr;
}

// В режиме скрытых «Сохранить» возвращает в список файлы со снятой галочкой.
function unchecked() {
  return state.rows.filter((r) => r.db_status === "HIDDEN" && !state.selected.has(r.id));
}

function updateControls() {
  const rows = visibleRows();
  const allSelected = rows.length > 0 && rows.every((r) => state.selected.has(r.id));
  el.chkAll.checked = allSelected;
  el.selectAll.title = allSelected ? "Снять выделение" : "Выделить все";
  el.count.textContent = String(state.selected.size);
  el.hide.disabled = state.hiddenMode || state.selected.size === 0;
  el.save.disabled = state.hiddenMode
    ? unchecked().length === 0
    : state.selected.size === 0 || state.tasksRunning;
  el.save.title = state.hiddenMode
    ? "Вернуть в список файлы со снятой галочкой"
    : "Сохранить выделенные файлы";
  el.queries.disabled = state.hiddenMode || state.selected.size === 0 || state.tasksRunning;
  el.showHidden.classList.toggle("active", state.hiddenMode);
  el.showHidden.title = state.hiddenMode ? "Вернуться к списку файлов" : "Показать скрытые файлы";
  el.search.disabled = state.searching;
  el.stop.disabled = !state.searching;
}

function setStatus(text, progress) {
  el.status.textContent = text;
  el.status.title = text;
  el.progress.hidden = progress == null;
  if (progress != null) el.progress.value = progress;
}

function showError(text) {
  $("error-text").textContent = text;
  $("error-popup").hidden = false;
}

function confirmDialog(text) {
  return new Promise((resolve) => {
    $("confirm-text").textContent = text;
    $("confirm-popup").hidden = false;
    const done = (answer) => {
      $("confirm-popup").hidden = true;
      $("confirm-yes").onclick = null;
      $("confirm-no").onclick = null;
      resolve(answer);
    };
    $("confirm-yes").onclick = () => done(true);
    $("confirm-no").onclick = () => done(false);
  });
}

// Выбор варианта «Сформировать запросы»: "by_type", "combined" или null (отмена).
function queriesModeDialog() {
  return new Promise((resolve) => {
    const popup = $("queries-mode-popup");
    const buttons = ["queries-mode-by-type", "queries-mode-combined", "queries-mode-cancel"];
    const done = (answer) => {
      popup.hidden = true;
      buttons.forEach((id) => { $(id).onclick = null; });
      resolve(answer);
    };
    $("queries-mode-by-type").onclick = () => done("by_type");
    $("queries-mode-combined").onclick = () => done("combined");
    $("queries-mode-cancel").onclick = () => done(null);
    popup.hidden = false;
  });
}

// ---------- Выделение ----------

function toggle(id, on) {
  if (on) state.selected.add(id); else state.selected.delete(id);
  render();
}

function toggleAll() {
  const rows = visibleRows();
  const allSelected = rows.length > 0 && rows.every((r) => state.selected.has(r.id));
  for (const row of rows) {
    if (allSelected) state.selected.delete(row.id); else state.selected.add(row.id);
  }
  render();
}

// ---------- Опрос статуса ----------

function startPolling() {
  if (state.timer) return;
  state.timer = setInterval(poll, POLL_MS);
}

function stopPolling() {
  clearInterval(state.timer);
  state.timer = null;
}

async function poll() {
  const status = await api().get_status();
  const search = status.search, tasks = status.tasks;
  state.searching = search.running;
  state.tasksRunning = tasks.running;

  if (search.running) {
    setStatus(search.stopping ? "Останавливается..." : `Идет поиск... обработано файлов: ${search.processed_files}`, null);
    el.progress.hidden = false;
    el.progress.removeAttribute("value");
  } else if (tasks.running) {
    setStatus(`Обработка... в очереди: ${tasks.pending}, готово: ${tasks.processed}`, null);
    el.progress.hidden = false;
    el.progress.removeAttribute("value");
  }
  await refresh();

  if (!search.running && !tasks.running) {
    stopPolling();
    const errors = [...(search.errors || []), ...(tasks.errors || [])];
    if (state.stoppedByUser || search.stopped) setStatus("Остановлено пользователем", null);
    else if (errors.length) setStatus(`Готово, ошибок: ${errors.length}`, null);
    else setStatus("Готово", null);
    state.stoppedByUser = false;
    updateControls();
    if (errors.length) showError(errors.join("\n"));
  }
}

// ---------- Действия ----------

async function onSearch() {
  if (!searchDirs().length) {
    openSettings();
    return;
  }
  runSearch();
}

async function runSearch() {
  state.searching = true;
  state.stoppedByUser = false;
  setStatus("Идет поиск...", null);
  updateControls();
  // При выключенном фоновом режиме start_search возвращается после конца поиска,
  // поэтому опрос запускаем отдельно и с небольшой задержкой (поиск должен успеть стартовать).
  setTimeout(startPolling, 300);
  const result = await api().start_search(searchDirs(), "*", el.background.checked);
  if (result.status === "error") {
    state.searching = false;
    setStatus("Готово", null);
    showError(result.message);
    updateControls();
  }
}

async function onStop() {
  state.stoppedByUser = true;
  await api().stop_search();
  setStatus("Останавливается...", null);
}

async function onAdd() {
  const paths = await api().add_files_dialog();
  if (!paths.length) return;
  setStatus("Обработка...", null);
  const result = await api().process_manual_add(paths);
  await refresh();
  if (result.errors && result.errors.length) showError(result.errors.join("\n"));
  setStatus(`Добавлено файлов: ${result.added}`, null);
}

async function onHide() {
  const ids = [...state.selected];
  if (!ids.length) return;
  if (!(await confirmDialog("Скрыть выделенные файлы?"))) return;
  const result = await api().hide_files(ids);
  state.selected.clear();
  await refresh();
  setStatus(`Скрыто файлов: ${result.changed}`, null);
}

function leaveHiddenMode() {
  state.hiddenMode = false;
  state.selected.clear();
}

async function onToggleHidden() {
  if (state.hiddenMode) {
    leaveHiddenMode();
  } else {
    state.hiddenMode = true;
    // Скрытые файлы показываются с установленными галочками.
    state.selected = new Set(state.rows.filter((r) => r.db_status === "HIDDEN").map((r) => r.id));
  }
  render();
}

async function onSave() {
  if (state.hiddenMode) {
    const ids = unchecked().map((r) => r.id);
    if (!ids.length) return;
    const result = await api().restore_files(ids);
    await refresh();
    setStatus(`Возвращено в список: ${result.changed}`, null);
    return;
  }
  const ids = [...state.selected];
  if (!ids.length) return;
  // Проверка комплекта: документ не из своего комплекта — «Отмена» или «Принять всё равно».
  const kit = await api().check_kits(ids);
  const conflicts = (kit && kit.conflicts) || [];
  if (conflicts.length) {
    const shown = conflicts.slice(0, 10)
      .map((c) => `• ${c.path}\n   ${c.message}`).join("\n");
    const more = conflicts.length > 10 ? `\n… и ещё ${conflicts.length - 10}` : "";
    const accept = window.confirm(
      `Документы не принадлежат комплекту (${conflicts.length}):\n${shown}${more}\n\n` +
      "ОК — принять всё равно (файлы будут помечены ⓘ), Отмена — не сохранять.");
    if (!accept) {
      setStatus("Сохранение отменено: документы не из комплекта", null);
      return;
    }
  }
  const queued = await api().process_selected(ids, conflicts.map((c) => c.id));
  if (queued && queued.queued === 0) {
    setStatus("Выбранные файлы уже сохранены и не изменились", null);
    return;
  }
  state.tasksRunning = true;
  setStatus("Обработка...", null);
  updateControls();
  startPolling();
}

// Диалог решений по заголовкам без роли. Возвращает решения или null при отмене.
function headersDialog(data) {
  return new Promise((resolve) => {
    const list = $("headers-list");
    list.replaceChildren();
    const rows = [];
    for (const item of data.unresolved) {
      const box = document.createElement("div");
      box.className = "header-item";
      const title = document.createElement("div");
      title.className = "header-title";
      title.textContent = `«${item.header}» — в ${item.count} CSV`;
      box.appendChild(title);
      for (const f of item.files) {
        const where = document.createElement("div");
        where.className = "muted";
        where.textContent = `${f.path || f.filename}, колонка ${f.column}`;
        if (f.path) {
          where.style.cursor = "pointer";
          where.title = "Щелчок — открыть файл в Word";
          where.addEventListener("click", async () => {
            const res = await api().open_document(f.path);
            if (res && res.status !== "ok") alert(res.message || "Не удалось открыть файл");
          });
        }
        box.appendChild(where);
      }
      if (item.suspicious) {
        const warn = document.createElement("div");
        warn.className = "header-warn";
        warn.textContent = "Похоже на строку данных, а не шапку: проверьте файл, роль не создавайте.";
        box.appendChild(warn);
      }
      const action = document.createElement("select");
      for (const [value, label] of [["skip", "Пропустить"], ["assign", "Назначить существующей"],
                                    ["new", "Новая роль"], ["ignore", "Игнорировать всегда"]]) {
        action.add(new Option(label, value));
      }
      const role = document.createElement("select");
      const cands = item.candidates.map((c) => c.canonical);
      const labels = new Map(item.candidates.map((c) => [c.canonical, ` (${c.score})`]));
      for (const name of [...cands, ...data.roles.filter((r) => !cands.includes(r))]) {
        role.add(new Option(name + (labels.get(name) || ""), name));
      }
      const newName = document.createElement("input");
      newName.type = "text";
      newName.value = item.header;
      newName.title = "Имя новой роли";
      const sync = () => {
        role.hidden = action.value !== "assign";
        newName.hidden = action.value !== "new";
      };
      action.addEventListener("change", sync);
      sync();
      const line = document.createElement("div");
      line.className = "dict-row";
      line.append(action, role, newName);
      box.appendChild(line);
      list.appendChild(box);
      rows.push({ item, action, role, newName });
    }
    const popup = $("headers-popup");
    const done = (answer) => {
      popup.hidden = true;
      $("headers-apply").onclick = null;
      $("headers-cancel").onclick = null;
      resolve(answer);
    };
    $("headers-apply").onclick = () => done(rows.map((r) => ({
      header: r.item.header,
      action: r.action.value,
      role: r.action.value === "new" ? r.newName.value : r.role.value,
    })));
    $("headers-cancel").onclick = () => done(null);
    popup.hidden = false;
  });
}

async function onBuildQueries() {
  if (state.tasksRunning) return;
  const ids = [...state.selected];
  if (!ids.length) return;
  const mode = await queriesModeDialog();
  if (mode === null) return;
  setStatus("Проверка заголовков...", null);
  const check = await api().check_headers(ids);
  if (check.status === "ok" && check.unresolved.length) {
    const decisions = await headersDialog(check);
    if (decisions === null) {
      setStatus("Формирование запросов отменено", null);
      return;
    }
    const applied = await api().apply_header_decisions(decisions);
    if (applied.status !== "ok") showError("Не все решения применены:\n" + applied.errors.join("\n"));
  }
  setStatus("Формирование запросов...", null);
  const result = await api().build_queries(ids, mode);
  if (result.status !== "ok") {
    setStatus("Запросы не сформированы", null);
    showError(result.message || "Не удалось сформировать запросы");
    return;
  }
  const rows = result.books.reduce((sum, b) => sum + b.rows, 0);
  const skipped = (result.skipped || []).length;
  setStatus(`Запросы сформированы: книг ${result.books.length}, строк ${rows}` +
    (skipped ? `, пропущено файлов ${skipped}` : ""), null);
  const notes = [];
  if (skipped) {
    notes.push("Пропущены файлы:\n" + result.skipped.map((s) => `${s.filename}: ${s.reason}`).join("\n"));
  }
  const ambiguous = result.books.flatMap((b) => b.ambiguous_versions || []);
  if (ambiguous.length) {
    notes.push("Одна версия документа (шифр, номер и дата изменения) найдена в нескольких файлах. " +
      "Связь ВОР и СО будет неоднозначной: выберите в таблице нужный файл или уберите лишний и сформируйте запросы заново.\n" +
      ambiguous.map((a) => `${a.doc_code}, изм. ${a.revision || "—"}, ${a.revision_date || "без даты"}:\n  ` +
        a.files.map((f) => f.filename).join("\n  ")).join("\n"));
  }
  if (notes.length) showError(notes.join("\n\n"));
}

async function openCsv(row) {
  if (!row.csv_path) {
    setStatus("У файла нет сохранённого CSV", null);
    return;
  }
  const result = await api().open_csv(row.id);
  if (result.status !== "ok") showError(result.message || "Не удалось открыть CSV");
}

async function onExit() {
  await api().exit_app();
}

async function onClearDb() {
  const ok = await confirmDialog(
    "Очистить базу данных?\nВсе записи о файлах и все CSV будут удалены. Действие необратимо.");
  if (!ok) return;
  const result = await api().clear_database();
  if (result.status !== "ok") {
    showError(result.message || "Не удалось очистить базу данных");
    return;
  }
  $("settings-popup").hidden = true;
  state.selected.clear();
  state.hiddenMode = false;
  await refresh();
  setStatus(`База очищена: записей ${result.records}, CSV ${result.csv_deleted}`, null);
}

// ---------- Комплекты поиска и типы документов (настройки) ----------

async function loadSettings() {
  let settings = null;
  try { settings = await api().get_settings(); } catch (e) { settings = null; }
  settings = settings || {};
  state.root = typeof settings.root === "string" ? settings.root : "";
  state.kits = Array.isArray(settings.kits) ? settings.kits.filter(Boolean) : [];
  if (Array.isArray(settings.known_types)) state.knownTypes = settings.known_types;
  state.hideUnknown = settings.hide_unknown === true;
  $("chk-hide-unknown").checked = state.hideUnknown;
  state.typeAliases = settings.type_aliases && typeof settings.type_aliases === "object" ? settings.type_aliases : {};
  state.searchByType = settings.search_by_type === true;
  $("chk-search-by-type").checked = state.searchByType;
  state.folderFilters = Array.isArray(settings.folder_filters) ? settings.folder_filters : [];
  if (typeof settings.background_mode === "boolean") el.background.checked = settings.background_mode;
  state.interval = Number(settings.interval_minutes) || 60;
  $("input-interval").value = state.interval;
  applyUi(settings.ui);
  if (state.root) await loadSubfolders();
}

async function persistSettings() {
  const minutes = Math.max(1, Math.min(1440, parseInt($("input-interval").value, 10) || state.interval || 60));
  state.interval = minutes;
  try {
    await api().save_settings({
      root: state.root,
      kits: state.kits,
      directories: searchDirs(),
      known_types: state.knownTypes,
      hide_unknown: state.hideUnknown,
      type_aliases: state.typeAliases,
      search_by_type: state.searchByType,
      folder_filters: state.folderFilters || [],
      background_mode: el.background.checked,
      interval_minutes: minutes,
    });
  } catch (e) {
    showError(`Не удалось сохранить настройки: ${e}`);
  }
}

async function loadSubfolders() {
  const result = await api().list_subfolders(state.root);
  state.subfolders = result.status === "ok" ? result.folders : [];
  if (result.status !== "ok") showError(result.message || "Не удалось прочитать корневую папку");
  // Выбранные комплекты, которых больше нет в корне, отбрасываем.
  state.kits = state.kits.filter((k) => state.subfolders.includes(k));
}

// Фоновый поиск: при включённом режиме и хотя бы одной папке ищем сразу и затем каждые N минут.
function scheduleBackground() {
  if (state.bgTimer) clearInterval(state.bgTimer);
  state.bgTimer = null;
  if (!el.background.checked || !searchDirs().length) return;
  state.bgTimer = setInterval(backgroundTick, state.interval * 60000);
}

function backgroundTick() {
  if (!el.background.checked || !searchDirs().length) return;
  if (state.searching || state.tasksRunning) return;
  runSearch();
}

async function onSettingsChanged(runNow) {
  await persistSettings();
  $("input-interval").value = state.interval;
  scheduleBackground();
  if (runNow) backgroundTick();
}

function saveKits() {
  renderKits();
  onSettingsChanged(true);
}

function renderKits() {
  const dirs = searchDirs().length;
  el.settings.title = dirs
    ? `Настройки (комплектов для поиска: ${dirs})`
    : "Настройки (комплекты для поиска не выбраны)";
  $("root-path").textContent = state.root || "Корневая папка не задана";
  $("root-path").title = state.root;
  const list = $("kits-list");
  list.replaceChildren();
  for (const name of state.subfolders) {
    const li = document.createElement("li");
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = state.kits.includes(name);
    box.addEventListener("change", () => {
      state.kits = box.checked
        ? [...state.kits, name]
        : state.kits.filter((k) => k !== name);
      saveKits();
    });
    label.append(box, " " + name);
    label.title = name;
    li.appendChild(label);
    list.appendChild(li);
  }
  const all = $("kits-all");
  all.disabled = !state.subfolders.length;
  all.checked = state.subfolders.length > 0 && state.subfolders.every((n) => state.kits.includes(n));
  all.onchange = () => {
    state.kits = all.checked ? [...state.subfolders] : [];
    saveKits();
  };
  $("kits-empty").hidden = state.subfolders.length > 0;
  $("kits-empty").textContent = state.root ? "В корневой папке нет вложенных папок." : "Выберите корневую папку.";
}

function openSettings() {
  renderKits();
  $("settings-popup").hidden = false;
}

async function onChooseRoot() {
  const folder = await api().choose_folder();
  if (!folder || folder === state.root) return;
  state.root = folder;
  state.kits = [];
  await loadSubfolders();
  saveKits();
}

// ---------- Известные типы документов ----------

const types = { selected: null, alias: null };

function renderTypes() {
  const known = $("types-known");
  known.replaceChildren();
  if (!state.knownTypes.includes(types.selected)) types.selected = null;
  for (const name of state.knownTypes) {
    const count = (state.typeAliases[name] || []).length;
    known.appendChild(dictItem(count ? `${name} (${count})` : name, name === types.selected, () => {
      types.selected = name;
      types.alias = null;
      $("types-name").value = name;
      $("types-alias-name").value = "";
      renderTypes();
    }));
  }
  $("types-selected").textContent = types.selected ? `Алиасы: ${types.selected}` : "Алиасы";
  const aliasList = $("types-alias");
  aliasList.replaceChildren();
  const aliases = types.selected ? state.typeAliases[types.selected] || [] : [];
  if (!aliases.includes(types.alias)) types.alias = null;
  for (const alias of aliases) {
    aliasList.appendChild(dictItem(alias, alias === types.alias, () => {
      types.alias = alias;
      $("types-alias-name").value = alias;
      renderTypes();
    }));
  }
  const found = $("types-found");
  found.replaceChildren();
  const inDb = [...new Set(state.rows.map((r) => r.doc_type).filter(Boolean))]
    .filter((t) => !state.knownTypes.includes(t)).sort((a, b) => a.localeCompare(b, "ru"));
  for (const name of inDb) {
    const count = state.rows.filter((r) => r.doc_type === name).length;
    found.appendChild(dictItem(`${name} (${count})`, false, () => typesChange([...state.knownTypes, name])));
  }
}

function typesChange(list) {
  state.knownTypes = [...new Set(list)];
  persistSettings();
  renderTypes();
  render();
}

function onTypeAdd() {
  const name = dictValue("types-name").toUpperCase();
  if (!name) return;
  types.selected = name;
  typesChange([...state.knownTypes, name]);
}

function onTypeRename() {
  const name = dictValue("types-name").toUpperCase();
  if (!types.selected || !name) return showError("Выберите тип в списке и введите новое имя в поле.");
  const old = types.selected;
  types.selected = name;
  if (old !== name && state.typeAliases[old]) {
    state.typeAliases[name] = [...new Set([...(state.typeAliases[name] || []), ...state.typeAliases[old]])];
    delete state.typeAliases[old];
  }
  typesChange(state.knownTypes.map((t) => (t === old ? name : t)));
}

function aliasChange(list) {
  if (!types.selected) return;
  if (list.length) state.typeAliases[types.selected] = list;
  else delete state.typeAliases[types.selected];
  persistSettings();
  renderTypes();
}

function onTypeAliasAdd() {
  const text = dictValue("types-alias-name");
  if (!types.selected) return showError("Сначала выберите известный тип в списке.");
  if (!text) return;
  const list = state.typeAliases[types.selected] || [];
  if (list.some((a) => a.toLowerCase() === text.toLowerCase())) return;
  types.alias = text;
  aliasChange([...list, text]);
}

function onTypeAliasRename() {
  const text = dictValue("types-alias-name");
  if (!types.alias || !text) return showError("Выберите алиас в списке и введите новое написание в поле.");
  const old = types.alias;
  types.alias = text;
  aliasChange([...new Set((state.typeAliases[types.selected] || []).map((a) => (a === old ? text : a)))]);
}

function onTypeAliasDelete() {
  if (!types.alias) return;
  const old = types.alias;
  types.alias = null;
  $("types-alias-name").value = "";
  aliasChange((state.typeAliases[types.selected] || []).filter((a) => a !== old));
}

function onSearchByType() {
  state.searchByType = $("chk-search-by-type").checked;
  persistSettings();
}

function onTypeDelete() {
  if (!types.selected) return;
  const old = types.selected;
  types.selected = null;
  types.alias = null;
  $("types-name").value = "";
  delete state.typeAliases[old];
  typesChange(state.knownTypes.filter((t) => t !== old));
}

function onHideUnknown() {
  state.hideUnknown = $("chk-hide-unknown").checked;
  if (state.hideUnknown) {
    const visible = new Set(visibleRows().map((r) => r.id));
    for (const id of [...state.selected]) if (!visible.has(id)) state.selected.delete(id);
  }
  persistSettings();
  render();
}

function openTypes() {
  $("types-name").value = "";
  types.selected = null;
  renderTypes();
  $("types-popup").hidden = false;
}

// ---------- Фильтр папок поиска ----------

const folders = { selected: null };

function renderFolders() {
  const list = $("folders-list");
  list.replaceChildren();
  const items = state.folderFilters || [];
  if (!items.includes(folders.selected)) folders.selected = null;
  for (const text of items) {
    list.appendChild(dictItem(text, text === folders.selected, () => {
      folders.selected = text;
      $("folders-name").value = text;
      renderFolders();
    }));
  }
}

function foldersChange(list) {
  state.folderFilters = [...new Set(list)];
  persistSettings();
  renderFolders();
}

function onFolderAdd() {
  const text = dictValue("folders-name");
  if (!text) return;
  const items = state.folderFilters || [];
  if (items.some((t) => t.toLowerCase() === text.toLowerCase())) return;
  folders.selected = text;
  foldersChange([...items, text]);
}

function onFolderRename() {
  const text = dictValue("folders-name");
  if (!folders.selected || !text) return showError("Выберите подстроку в списке и введите новое написание в поле.");
  const old = folders.selected;
  folders.selected = text;
  foldersChange((state.folderFilters || []).map((t) => (t === old ? text : t)));
}

function onFolderDelete() {
  if (!folders.selected) return;
  const old = folders.selected;
  folders.selected = null;
  $("folders-name").value = "";
  foldersChange((state.folderFilters || []).filter((t) => t !== old));
}

function openFolders() {
  $("folders-name").value = "";
  folders.selected = null;
  renderFolders();
  $("folders-popup").hidden = false;
}

// ---------- Справочник заголовков ----------

const dict = { data: null, selected: null, alias: null, ignored: null };

function dictItem(text, selected, onClick) {
  const li = document.createElement("li");
  li.textContent = text;
  if (selected) li.className = "selected";
  li.addEventListener("click", onClick);
  return li;
}

function renderDictionary() {
  const data = dict.data;
  if (!data.canonical.some((c) => c.name === dict.selected)) {
    dict.selected = data.canonical.length ? data.canonical[0].name : null;
  }
  const canon = $("dict-canon");
  canon.replaceChildren();
  for (const c of data.canonical) {
    const text = `${c.name} (${c.synonyms.length})` + (c.user_created ? " *" : "");
    canon.appendChild(dictItem(text, c.name === dict.selected, () => {
      dict.selected = c.name;
      dict.alias = null;
      $("dict-canon-name").value = c.name;
      $("dict-alias-name").value = "";
      renderDictionary();
    }));
  }
  const current = data.canonical.find((c) => c.name === dict.selected);
  $("dict-selected").textContent = current ? `Синонимы: ${current.name}` : "Синонимы";
  const alias = $("dict-alias");
  alias.replaceChildren();
  const keys = current ? current.synonyms : [];
  if (!keys.includes(dict.alias)) dict.alias = null;
  for (const key of keys) {
    const label = (current.labels && current.labels[key]) || key;
    alias.appendChild(dictItem(label, key === dict.alias, () => {
      dict.alias = key;
      $("dict-alias-name").value = label;
      renderDictionary();
    }));
  }
  const ignored = $("dict-ignored");
  ignored.replaceChildren();
  if (!data.ignored.some((i) => i.key === dict.ignored)) dict.ignored = null;
  for (const item of data.ignored) {
    ignored.appendChild(dictItem(item.raw, item.key === dict.ignored, () => {
      dict.ignored = item.key;
      $("dict-ignored-name").value = item.raw;
      renderDictionary();
    }));
  }
}

async function dictEdit(op, args) {
  const result = await api().edit_dictionary(op, args);
  if (result.status !== "ok") {
    showError(result.message || "Не удалось изменить справочник");
    return false;
  }
  dict.data = result;
  renderDictionary();
  return true;
}

async function openDictionary() {
  const result = await api().get_dictionary();
  if (result.status !== "ok") {
    showError(result.message || "Не удалось прочитать справочник");
    return;
  }
  dict.data = result;
  renderDictionary();
  $("dict-popup").hidden = false;
}

function dictValue(id) {
  return $(id).value.trim();
}

// Имена
async function onCanonAdd() {
  const name = dictValue("dict-canon-name");
  if (name && await dictEdit("add_canonical", { name })) {
    dict.selected = name;
    renderDictionary();
  }
}

async function onCanonRename() {
  const name = dictValue("dict-canon-name");
  if (!dict.selected || !name) return showError("Выберите имя в списке и введите новое в поле.");
  if (await dictEdit("rename_canonical", { old: dict.selected, new: name })) {
    dict.selected = name;
    renderDictionary();
  }
}

async function onCanonDelete() {
  if (!dict.selected) return;
  if (!(await confirmDialog(`Удалить имя «${dict.selected}» и все его синонимы?`))) return;
  if (await dictEdit("delete_canonical", { name: dict.selected })) $("dict-canon-name").value = "";
}

// Синонимы
async function onAliasAdd() {
  const text = dictValue("dict-alias-name");
  if (!dict.selected || !text) return;
  await dictEdit("add_alias", { canonical: dict.selected, text });
}

async function onAliasRename() {
  const text = dictValue("dict-alias-name");
  if (!dict.alias || !text) return showError("Выберите синоним в списке и введите новое написание в поле.");
  await dictEdit("rename_alias", { key: dict.alias, canonical: dict.selected, text });
}

async function onAliasDelete() {
  if (!dict.alias) return;
  if (await dictEdit("remove_alias", { key: dict.alias })) {
    dict.alias = null;
    $("dict-alias-name").value = "";
  }
}

// Игнорируемые заголовки
async function onIgnoredAdd() {
  const text = dictValue("dict-ignored-name");
  if (text) await dictEdit("ignore", { text });
}

async function onIgnoredRename() {
  const text = dictValue("dict-ignored-name");
  if (!dict.ignored || !text) return showError("Выберите заголовок в списке и введите новое написание в поле.");
  await dictEdit("rename_ignored", { key: dict.ignored, text });
}

async function onIgnoredDelete() {
  if (!dict.ignored) return;
  if (await dictEdit("unignore", { key: dict.ignored })) {
    dict.ignored = null;
    $("dict-ignored-name").value = "";
  }
}

// ---------- Запуск ----------

function bind() {
  el.search.addEventListener("click", onSearch);
  el.stop.addEventListener("click", onStop);
  el.add.addEventListener("click", onAdd);
  el.save.addEventListener("click", onSave);
  el.queries.addEventListener("click", onBuildQueries);
  el.hide.addEventListener("click", onHide);
  el.showHidden.addEventListener("click", onToggleHidden);
  el.exit.addEventListener("click", onExit);
  el.settings.addEventListener("click", openSettings);
  $("btn-root").addEventListener("click", onChooseRoot);
  $("btn-types").addEventListener("click", openTypes);
  $("btn-folders").addEventListener("click", openFolders);
  $("folders-add").addEventListener("click", onFolderAdd);
  $("folders-rename").addEventListener("click", onFolderRename);
  $("folders-delete").addEventListener("click", onFolderDelete);
  $("folders-close").addEventListener("click", () => { $("folders-popup").hidden = true; });
  $("types-add").addEventListener("click", onTypeAdd);
  $("types-rename").addEventListener("click", onTypeRename);
  $("types-delete").addEventListener("click", onTypeDelete);
  $("types-alias-add").addEventListener("click", onTypeAliasAdd);
  $("types-alias-rename").addEventListener("click", onTypeAliasRename);
  $("types-alias-delete").addEventListener("click", onTypeAliasDelete);
  $("chk-search-by-type").addEventListener("change", onSearchByType);
  $("types-close").addEventListener("click", () => { $("types-popup").hidden = true; });
  $("chk-hide-unknown").addEventListener("change", onHideUnknown);
  $("btn-clear-db").addEventListener("click", onClearDb);
  $("btn-dictionary").addEventListener("click", openDictionary);
  $("dict-canon-add").addEventListener("click", onCanonAdd);
  $("dict-canon-rename").addEventListener("click", onCanonRename);
  $("dict-canon-delete").addEventListener("click", onCanonDelete);
  $("dict-alias-add").addEventListener("click", onAliasAdd);
  $("dict-alias-rename").addEventListener("click", onAliasRename);
  $("dict-alias-delete").addEventListener("click", onAliasDelete);
  $("dict-ignored-add").addEventListener("click", onIgnoredAdd);
  $("dict-ignored-rename").addEventListener("click", onIgnoredRename);
  $("dict-ignored-delete").addEventListener("click", onIgnoredDelete);
  $("dict-close").addEventListener("click", () => { $("dict-popup").hidden = true; });
  $("settings-close").addEventListener("click", () => { $("settings-popup").hidden = true; });
  el.selectAll.addEventListener("click", toggleAll);
$("btn-toggle-tree").addEventListener("click", toggleTree);
  el.chkAll.addEventListener("change", toggleAll);
  el.filter.addEventListener("input", () => { state.filter = el.filter.value; saveUi(); render(); });
  $("error-close").addEventListener("click", () => { $("error-popup").hidden = true; });
  for (const th of document.querySelectorAll("th[data-sort]")) {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      state.sort = { key, dir: state.sort.key === key ? -state.sort.dir : 1 };
      saveUi();
      render();
    });
  }
  el.background.addEventListener("change", () => onSettingsChanged(el.background.checked));
  $("input-interval").addEventListener("change", () => onSettingsChanged(false));
}

async function init() {
  bind();
  render();
  try {
    console.log("ping:", await api().ping());
    await loadSettings();
    renderKits();
    await refresh();
    await poll();
    scheduleBackground();
    backgroundTick();
  } catch (error) {
    showError(String(error));
  }
}

window.addEventListener("pywebviewready", init);
