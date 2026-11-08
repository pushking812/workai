"use strict";

const POLL_MS = 700;
const COLUMNS = ["doc_code", "revision", "revision_date", "filename", "path", "status", "size", "file_mtime"];
const STATUS_LABELS = {
  FOUND: "Найден", EXISTS: "В базе", VARIANTS: "Вариант", SAVED: "Сохранён",
  PROCESSING: "Обработка", NEEDS_MAPPING: "Нужен маппинг", READY: "Готово", ERROR: "Ошибка",
};

const state = {
  rows: [],
  selected: new Set(),
  sort: { key: "doc_code", dir: 1 },
  filter: "",
  searching: false,
  tasksRunning: false,
  stoppedByUser: false,
  timer: null,
};

const $ = (id) => document.getElementById(id);
const el = {
  body: $("grid-body"), empty: $("empty"), status: $("status-text"), progress: $("progress"),
  search: $("btn-search"), stop: $("btn-stop"), add: $("btn-add"), save: $("btn-save"),
  folder: $("input-folder"), pickFolder: $("btn-folder"), filter: $("input-filter"),
  selectAll: $("btn-select-all"), chkAll: $("chk-all"), count: $("selected-count"),
  background: $("chk-background"),
};

function api() {
  return window.pywebview.api;
}

// ---------- Данные ----------

function mergeRows(data) {
  const found = new Map();
  for (const item of data.found || []) {
    if (item.file_id != null) found.set(item.file_id, item);
  }
  const rows = (data.files || []).map((row) => {
    const hit = found.get(row.id);
    return { ...row, status: hit ? hit.ui_status : row.status, db_status: row.status };
  });
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

function isInactive(row) {
  return row.status === "EXISTS";
}

function visibleRows() {
  const needle = state.filter.trim().toLowerCase();
  const rows = needle
    ? state.rows.filter((r) =>
        [r.doc_code, r.revision, r.revision_date, r.filename, r.path, STATUS_LABELS[r.status]]
          .some((v) => String(v ?? "").toLowerCase().includes(needle)))
    : [...state.rows];
  const { key, dir } = state.sort;
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
  td.textContent = text ?? "";
  if (className) td.className = className;
  if (className === "path" || className === "filename") td.title = text ?? "";
  return td;
}

function badge(row) {
  const span = document.createElement("span");
  span.className = "badge " + row.status;
  span.textContent = STATUS_LABELS[row.status] || row.status;
  if (row.status === "ERROR") {
    span.title = "Нажмите, чтобы увидеть текст ошибки";
    span.addEventListener("click", (e) => {
      e.stopPropagation();
      showError(row.error_message || "Текст ошибки не сохранён");
    });
  }
  return span;
}

function render() {
  const rows = visibleRows();
  el.body.replaceChildren();
  for (const row of rows) {
    const tr = document.createElement("tr");
    if (isInactive(row)) tr.classList.add("inactive");
    if (row.is_variant) tr.classList.add("variant");
    if (state.selected.has(row.id)) tr.classList.add("selected");

    const check = document.createElement("td");
    check.className = "col-check";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = state.selected.has(row.id);
    box.disabled = isInactive(row);
    box.addEventListener("change", () => toggle(row.id, box.checked));
    check.appendChild(box);
    tr.appendChild(check);

    tr.appendChild(cell(row.doc_code, "doc_code"));
    tr.appendChild(cell(row.revision, "revision"));
    tr.appendChild(cell(row.revision_date, "revision_date"));
    tr.appendChild(cell(row.filename, "filename"));
    tr.appendChild(cell(row.path, "path"));
    const status = document.createElement("td");
    status.appendChild(badge(row));
    tr.appendChild(status);
    tr.appendChild(cell(formatSize(row.size), "size"));
    tr.appendChild(cell(formatTime(row.file_mtime), "file_mtime"));
    el.body.appendChild(tr);
  }
  el.empty.hidden = rows.length > 0;
  for (const th of document.querySelectorAll("th[data-sort]")) {
    th.classList.toggle("sorted-asc", th.dataset.sort === state.sort.key && state.sort.dir === 1);
    th.classList.toggle("sorted-desc", th.dataset.sort === state.sort.key && state.sort.dir === -1);
  }
  updateControls();
}

function updateControls() {
  const selectable = visibleRows().filter((r) => !isInactive(r));
  const allSelected = selectable.length > 0 && selectable.every((r) => state.selected.has(r.id));
  el.chkAll.checked = allSelected;
  el.selectAll.textContent = allSelected ? "Снять выделение" : "Выделить все";
  el.count.textContent = "Выбрано: " + state.selected.size;
  el.save.disabled = state.selected.size === 0 || state.tasksRunning;
  el.search.disabled = state.searching;
  el.stop.disabled = !state.searching;
}

function setStatus(text, progress) {
  el.status.textContent = text;
  el.progress.hidden = progress == null;
  if (progress != null) el.progress.value = progress;
}

function showError(text) {
  $("error-text").textContent = text;
  $("error-popup").hidden = false;
}

// ---------- Выделение ----------

function toggle(id, on) {
  if (on) state.selected.add(id); else state.selected.delete(id);
  render();
}

function toggleAll() {
  const selectable = visibleRows().filter((r) => !isInactive(r));
  const allSelected = selectable.length > 0 && selectable.every((r) => state.selected.has(r.id));
  for (const row of selectable) {
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
  let folder = el.folder.value.trim();
  if (!folder) {
    folder = await api().choose_folder();
    if (!folder) return;
    el.folder.value = folder;
  }
  localStorage.setItem("folder", folder);
  const result = await api().start_search([folder], "*", true);
  if (result.status === "error") { showError(result.message); return; }
  state.searching = true;
  state.stoppedByUser = false;
  setStatus("Идет поиск...", null);
  updateControls();
  startPolling();
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

async function onSave() {
  const ids = [...state.selected];
  if (!ids.length) return;
  await api().process_selected(ids);
  state.tasksRunning = true;
  setStatus("Обработка...", null);
  updateControls();
  startPolling();
}

async function onPickFolder() {
  const folder = await api().choose_folder();
  if (folder) { el.folder.value = folder; localStorage.setItem("folder", folder); }
}

// ---------- Запуск ----------

function bind() {
  el.search.addEventListener("click", onSearch);
  el.stop.addEventListener("click", onStop);
  el.add.addEventListener("click", onAdd);
  el.save.addEventListener("click", onSave);
  el.pickFolder.addEventListener("click", onPickFolder);
  el.selectAll.addEventListener("click", toggleAll);
  el.chkAll.addEventListener("change", toggleAll);
  el.filter.addEventListener("input", () => { state.filter = el.filter.value; render(); });
  $("error-close").addEventListener("click", () => { $("error-popup").hidden = true; });
  for (const th of document.querySelectorAll("th[data-sort]")) {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      state.sort = { key, dir: state.sort.key === key ? -state.sort.dir : 1 };
      render();
    });
  }
  el.folder.value = localStorage.getItem("folder") || "";
}

async function init() {
  bind();
  render();
  try {
    console.log("ping:", await api().ping());
    await refresh();
    await poll();
  } catch (error) {
    showError(String(error));
  }
}

window.addEventListener("pywebviewready", init);
