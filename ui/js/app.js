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
  dirs: [],
  interval: 60,
  bgTimer: null,
  expanded: new Set(),
  treeMode: localStorage.getItem("treeMode") === "section-type" ? "section-type" : "type-section",
};

const NO_TYPE = "Без типа";
const NO_SECTION = "Без раздела";

const $ = (id) => document.getElementById(id);
const el = {
  body: $("grid-body"), empty: $("empty"), status: $("status-text"), progress: $("progress"),
  search: $("btn-search"), stop: $("btn-stop"), add: $("btn-add"), save: $("btn-save"),
  hide: $("btn-hide"), showHidden: $("btn-show-hidden"), exit: $("btn-exit"),
  settings: $("btn-settings"), filter: $("input-filter"),
  selectAll: $("btn-select-all"), chkAll: $("chk-all"), count: $("selected-count"),
  background: $("chk-background"),
};

function api() {
  return window.pywebview.api;
}

$("select-tree").value = state.treeMode;
$("select-tree").addEventListener("change", (e) => {
  state.treeMode = e.target.value;
  localStorage.setItem("treeMode", state.treeMode);
  saveUi();
  render();
});

// Состояние основного окна (дерево, сортировка, фильтр, раскрытые группы) хранится в конфиге.
let uiTimer = null;
function saveUi() {
  clearTimeout(uiTimer);
  uiTimer = setTimeout(() => {
    try {
      api().save_settings({
        ui: {
          tree_mode: state.treeMode,
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
  if (ui.tree_mode) {
    state.treeMode = ui.tree_mode;
    $("select-tree").value = state.treeMode;
  }
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

function visibleRows() {
  const needle = state.filter.trim().toLowerCase();
  let rows = state.rows.filter((r) => (r.db_status === "HIDDEN") === state.hiddenMode);
  if (needle) {
    rows = rows.filter((r) =>
      [r.doc_code, r.revision, r.revision_date, r.filename, r.path, STATUS_LABELS[r.status]]
        .some((v) => String(v ?? "").toLowerCase().includes(needle)));
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

// Структура дерева: "type-section" (Тип -> Код раздела) или "section-type"
function buildTree(rows) {
  const swap = state.treeMode === "section-type";
  const top = new Map();
  for (const row of rows) {
    const type = row.doc_type || NO_TYPE;
    const section = row.section_code || NO_SECTION;
    const [a, b] = swap ? [section, type] : [type, section];
    if (!top.has(a)) top.set(a, new Map());
    const sub = top.get(a);
    if (!sub.has(b)) sub.set(b, []);
    sub.get(b).push(row);
  }
  const byName = (x, y) => x[0].localeCompare(y[0], "ru", { numeric: true });
  const mode = state.treeMode;
  return [...top].sort(byName).map(([a, sub]) => ({
    name: a,
    key: mode + ":t:" + a,
    sections: [...sub].sort(byName).map(([b, files]) => ({
      name: b, key: mode + ":s:" + a + "|" + b, files,
    })),
  }));
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

function render() {
  const rows = visibleRows();
  el.body.replaceChildren();
  for (const type of buildTree(rows)) {
    const typeFiles = type.sections.flatMap((s) => s.files);
    const head = groupRow(type.name, type.key, 1, typeFiles);
    el.body.appendChild(head.tr);
    if (!head.open) continue;
    for (const section of type.sections) {
      const sub = groupRow(section.name, section.key, 2, section.files);
      el.body.appendChild(sub.tr);
      if (!sub.open) continue;
      for (const row of section.files) el.body.appendChild(fileRow(row));
    }
  }
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

  tr.appendChild(cell(row.doc_code, "doc_code"));
  tr.appendChild(cell(row.revision, "revision"));
  tr.appendChild(cell(row.revision_date, "revision_date"));
  tr.appendChild(cell(row.filename, "filename"));
  tr.appendChild(cell(row.dir, "path"));
  const status = document.createElement("td");
  status.appendChild(badge(row));
  tr.appendChild(status);
  tr.appendChild(cell(formatSize(row.size), "size"));
  tr.appendChild(cell(formatTime(row.file_mtime), "file_mtime"));
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
  if (!state.dirs.length) {
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
  const result = await api().start_search(state.dirs, "*", el.background.checked);
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
  await api().process_selected(ids);
  state.tasksRunning = true;
  setStatus("Обработка...", null);
  updateControls();
  startPolling();
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

// ---------- Папки поиска (настройки) ----------

async function loadSettings() {
  let settings = null;
  try { settings = await api().get_settings(); } catch (e) { settings = null; }
  settings = settings || {};
  // Однократный перенос папок из прежнего хранилища браузера.
  let dirs = Array.isArray(settings.directories) ? settings.directories : [];
  let migrated = false;
  if (!dirs.length) {
    try { dirs = JSON.parse(localStorage.getItem("dirs") || "[]"); } catch (e) { dirs = []; }
    const legacy = localStorage.getItem("folder");
    if (!dirs.length && legacy) dirs = [legacy];
    migrated = dirs.length > 0;
  }
  state.dirs = Array.isArray(dirs) ? dirs.filter(Boolean) : [];
  if (typeof settings.background_mode === "boolean") el.background.checked = settings.background_mode;
  state.interval = Number(settings.interval_minutes) || 60;
  $("input-interval").value = state.interval;
  applyUi(settings.ui);
  if (migrated) await persistSettings();
}

async function persistSettings() {
  const minutes = Math.max(1, Math.min(1440, parseInt($("input-interval").value, 10) || state.interval || 60));
  state.interval = minutes;
  try {
    await api().save_settings({
      directories: state.dirs,
      background_mode: el.background.checked,
      interval_minutes: minutes,
    });
  } catch (e) {
    showError(`Не удалось сохранить настройки: ${e}`);
  }
}

// Фоновый поиск: при включённом режиме и хотя бы одной папке ищем сразу и затем каждые N минут.
function scheduleBackground() {
  if (state.bgTimer) clearInterval(state.bgTimer);
  state.bgTimer = null;
  if (!el.background.checked || !state.dirs.length) return;
  state.bgTimer = setInterval(backgroundTick, state.interval * 60000);
}

function backgroundTick() {
  if (!el.background.checked || !state.dirs.length) return;
  if (state.searching || state.tasksRunning) return;
  runSearch();
}

async function onSettingsChanged(runNow) {
  await persistSettings();
  $("input-interval").value = state.interval;
  scheduleBackground();
  if (runNow) backgroundTick();
}

function saveDirs() {
  renderDirs();
  onSettingsChanged(true);
}

function renderDirs() {
  el.settings.title = state.dirs.length
    ? `Настройки (папок поиска: ${state.dirs.length})`
    : "Настройки (папки поиска не заданы)";
  const list = $("dirs-list");
  list.replaceChildren();
  for (const dir of state.dirs) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = dir;
    name.title = dir;
    const remove = document.createElement("button");
    remove.textContent = "Удалить";
    remove.addEventListener("click", () => {
      state.dirs = state.dirs.filter((d) => d !== dir);
      saveDirs();
    });
    li.append(name, remove);
    list.appendChild(li);
  }
  $("dirs-empty").hidden = state.dirs.length > 0;
}

function openSettings() {
  renderDirs();
  $("settings-popup").hidden = false;
}

async function onAddDir() {
  const folder = await api().choose_folder();
  if (!folder || state.dirs.includes(folder)) return;
  state.dirs.push(folder);
  saveDirs();
}

// ---------- Запуск ----------

function bind() {
  el.search.addEventListener("click", onSearch);
  el.stop.addEventListener("click", onStop);
  el.add.addEventListener("click", onAdd);
  el.save.addEventListener("click", onSave);
  el.hide.addEventListener("click", onHide);
  el.showHidden.addEventListener("click", onToggleHidden);
  el.exit.addEventListener("click", onExit);
  el.settings.addEventListener("click", openSettings);
  $("btn-dir-add").addEventListener("click", onAddDir);
  $("btn-clear-db").addEventListener("click", onClearDb);
  $("settings-close").addEventListener("click", () => { $("settings-popup").hidden = true; });
  el.selectAll.addEventListener("click", toggleAll);
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
    renderDirs();
    await refresh();
    await poll();
    scheduleBackground();
    backgroundTick();
  } catch (error) {
    showError(String(error));
  }
}

window.addEventListener("pywebviewready", init);
