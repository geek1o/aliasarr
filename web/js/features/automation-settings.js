(function () {
  "use strict";

  const state = { tags: [], profiles: [], lists: [], indexers: [] };
  const el = id => document.getElementById(id);
  const safe = value => (typeof escapeHtml === "function" ? escapeHtml(String(value ?? "")) : String(value ?? ""));
  const notify = (message, error = false) => {
    if (typeof toast === "function") toast(message, error);
  };

  async function loadAutomationSettings() {
    try {
      const [tags, profiles, lists, settings, recycle, indexers] = await Promise.all([
        api("/api/v1/tags"),
        api("/api/v1/delay-profiles"),
        api("/api/v1/import-lists"),
        api("/api/v1/settings"),
        api("/api/v1/recycle-bin"),
        api("/api/v1/indexers"),
      ]);
      state.tags = tags || [];
      state.profiles = profiles || [];
      state.lists = lists || [];
      state.indexers = indexers || [];
      renderTags();
      renderProfiles();
      renderImportLists();
      renderRecycleBin(recycle || []);
      if (el("recycle-bin-enabled")) el("recycle-bin-enabled").checked = !!settings.recycle_bin_enabled;
      if (el("recycle-bin-days")) el("recycle-bin-days").value = settings.recycle_bin_retention_days || 30;
      if (window.lucide) window.lucide.createIcons();
    } catch (error) {
      notify(`Не удалось загрузить настройки автоматизации: ${error.message}`, true);
    }
  }

  function renderTags() {
    const container = el("automation-tags-list");
    const tagSelect = el("delay-tag");
    if (tagSelect) {
      tagSelect.innerHTML = `<option value="">Глобальный</option>${state.tags.map(tag => `<option value="${tag.id}">${safe(tag.name)}</option>`).join("")}`;
    }
    if (!container) return;
    if (!state.tags.length) {
      container.innerHTML = `<div class="automation-empty">Теги ещё не созданы</div>`;
      return;
    }
    const shows = window.CACHED_SHOWS || [];
    container.innerHTML = state.tags.map(tag => `
      <div class="automation-row">
        <div class="automation-row-main"><strong>${safe(tag.name)}</strong><span class="hint">Тайтлов: ${tag.show_ids.length}, индексаторов: ${tag.indexer_ids.length}</span></div>
        <select class="input input-small" id="tag-show-${tag.id}"><option value="">Тайтл…</option>${shows.map(show => `<option value="${show.id}">${safe(show.title)}</option>`).join("")}</select>
        <button class="btn btn-secondary btn-small" onclick="assignAutomationTag(${tag.id}, 'shows')">Назначить</button>
        <select class="input input-small" id="tag-indexer-${tag.id}"><option value="">Индексатор…</option>${state.indexers.map(indexer => `<option value="${indexer.id}">${safe(indexer.name)}</option>`).join("")}</select>
        <button class="btn btn-secondary btn-small" onclick="assignAutomationTag(${tag.id}, 'indexers')">Назначить</button>
        <button class="btn-icon-only danger" title="Удалить" onclick="deleteAutomationTag(${tag.id})"><i data-lucide="trash-2" class="ico-sm"></i></button>
      </div>`).join("");
  }

  async function createAutomationTag() {
    const input = el("automation-tag-name");
    const name = input?.value.trim();
    if (!name) return notify("Укажите название тега", true);
    try {
      await api("/api/v1/tags", { method: "POST", body: JSON.stringify({ name }) });
      input.value = "";
      await loadAutomationSettings();
    } catch (error) { notify(error.message, true); }
  }

  async function deleteAutomationTag(tagId) {
    if (typeof confirmModal === "function" && !(await confirmModal("Удалить тег и связанный профиль задержки?"))) return;
    try {
      await api(`/api/v1/tags/${tagId}`, { method: "DELETE" });
      await loadAutomationSettings();
    } catch (error) { notify(error.message, true); }
  }

  async function assignAutomationTag(tagId, kind) {
    const select = el(kind === "shows" ? `tag-show-${tagId}` : `tag-indexer-${tagId}`);
    if (!select?.value) return;
    try {
      await api(`/api/v1/tags/${tagId}/${kind}/${select.value}`, { method: "POST" });
      await loadAutomationSettings();
    } catch (error) { notify(error.message, true); }
  }

  function renderProfiles() {
    const container = el("delay-profiles-list");
    if (!container) return;
    container.innerHTML = state.profiles.length ? state.profiles.map(profile => {
      const tag = state.tags.find(item => item.id === profile.tag_id);
      return `<div class="automation-row"><div class="automation-row-main"><strong>${safe(profile.name)}</strong><span class="hint">${tag ? `Тег: ${safe(tag.name)}` : "Глобальный"} · Torrent ${profile.torrent_delay_minutes} мин · Usenet ${profile.usenet_delay_minutes} мин · ${safe(profile.preferred_protocol)}</span></div><button class="btn-icon-only danger" onclick="deleteDelayProfile(${profile.id})"><i data-lucide="trash-2" class="ico-sm"></i></button></div>`;
    }).join("") : `<div class="automation-empty">Профили задержки не настроены</div>`;
  }

  async function createDelayProfile() {
    const score = el("delay-cf-score")?.value.trim();
    const payload = {
      name: el("delay-name")?.value.trim() || "Delay Profile",
      tag_id: el("delay-tag")?.value ? Number(el("delay-tag").value) : null,
      preferred_protocol: el("delay-protocol")?.value || "torrent",
      torrent_delay_minutes: Number(el("delay-torrent-minutes")?.value || 0),
      usenet_delay_minutes: Number(el("delay-usenet-minutes")?.value || 0),
      bypass_if_highest_quality: !!el("delay-bypass-quality")?.checked,
      bypass_custom_format_score: score === "" ? null : Number(score),
      enabled: true,
    };
    try {
      await api("/api/v1/delay-profiles", { method: "POST", body: JSON.stringify(payload) });
      await loadAutomationSettings();
    } catch (error) { notify(error.message, true); }
  }

  async function deleteDelayProfile(profileId) {
    try {
      await api(`/api/v1/delay-profiles/${profileId}`, { method: "DELETE" });
      await loadAutomationSettings();
    } catch (error) { notify(error.message, true); }
  }

  function toggleImportListUsername() {
    if (el("import-list-username-wrap")) el("import-list-username-wrap").style.display = el("import-list-source")?.value === "trakt_list" ? "" : "none";
  }

  async function createImportList() {
    const payload = {
      name: el("import-list-name")?.value.trim(),
      source: el("import-list-source")?.value,
      source_id: el("import-list-source-id")?.value.trim(),
      api_key: el("import-list-api-key")?.value || null,
      username: el("import-list-username")?.value.trim() || null,
      enabled: true,
      interval_minutes: Number(el("import-list-interval")?.value || 360),
      include_movies: !!el("import-list-movies")?.checked,
      include_series: !!el("import-list-series")?.checked,
      include_crew: false,
      monitored: true,
      search_on_add: !!el("import-list-search")?.checked,
      tag_ids: [],
    };
    if (!payload.name || !payload.source_id) return notify("Укажите название и ID списка", true);
    try {
      await api("/api/v1/import-lists", { method: "POST", body: JSON.stringify(payload) });
      el("import-list-api-key").value = "";
      await loadAutomationSettings();
    } catch (error) { notify(error.message, true); }
  }

  function renderImportLists() {
    const container = el("import-lists-list");
    if (!container) return;
    container.innerHTML = state.lists.length ? state.lists.map(item => `
      <div class="automation-row"><div class="automation-row-main"><strong>${safe(item.name)}</strong><span class="hint">${safe(item.source)} · каждые ${item.interval_minutes} мин${item.last_error ? ` · Ошибка: ${safe(item.last_error)}` : ""}</span></div>
      <button class="btn btn-secondary btn-small" onclick="previewImportList(${item.id})">Предпросмотр</button><button class="btn btn-primary btn-small" onclick="syncImportList(${item.id})">Синхронизировать</button><button class="btn-icon-only danger" onclick="deleteImportList(${item.id})"><i data-lucide="trash-2" class="ico-sm"></i></button></div>`).join("") : `<div class="automation-empty">Списки импорта не настроены</div>`;
  }

  async function previewImportList(listId) {
    try {
      const result = await api(`/api/v1/import-lists/${listId}/preview`, { method: "POST" });
      notify(`Предпросмотр: новых ${result.add_count}, уже есть ${result.existing_count}, дублей ${result.duplicate_count}`);
    } catch (error) { notify(error.message, true); }
  }

  async function syncImportList(listId) {
    try {
      await api(`/api/v1/import-lists/${listId}/sync`, { method: "POST" });
      notify("Синхронизация поставлена в очередь");
      if (typeof loadTasksStatus === "function") loadTasksStatus(true);
    } catch (error) { notify(error.message, true); }
  }

  async function deleteImportList(listId) {
    try {
      await api(`/api/v1/import-lists/${listId}`, { method: "DELETE" });
      await loadAutomationSettings();
    } catch (error) { notify(error.message, true); }
  }

  async function loadRecycleBin() {
    try { renderRecycleBin(await api("/api/v1/recycle-bin")); }
    catch (error) { notify(error.message, true); }
  }

  function renderRecycleBin(entries) {
    const container = el("recycle-bin-list");
    if (!container) return;
    container.innerHTML = entries.length ? entries.map(entry => `
      <div class="automation-row"><div class="automation-row-main"><strong>${safe(entry.original_path.split(/[\\/]/).pop())}</strong><span class="hint">${safe(entry.original_path)} · ${typeof formatSize === "function" ? formatSize(entry.size_bytes) : entry.size_bytes}</span></div><button class="btn btn-secondary btn-small" onclick="restoreRecycleEntry('${safe(entry.id)}')">Восстановить</button><button class="btn-icon-only danger" onclick="purgeRecycleEntry('${safe(entry.id)}')"><i data-lucide="trash-2" class="ico-sm"></i></button></div>`).join("") : `<div class="automation-empty">Корзина пуста</div>`;
    if (window.lucide) window.lucide.createIcons();
  }

  async function saveRecycleBinSettings() {
    try {
      await api("/api/v1/settings", { method: "PUT", body: JSON.stringify({ recycle_bin_enabled: !!el("recycle-bin-enabled")?.checked, recycle_bin_retention_days: Number(el("recycle-bin-days")?.value || 30) }) });
      notify("Настройки корзины сохранены");
    } catch (error) { notify(error.message, true); }
  }

  async function restoreRecycleEntry(entryId) {
    try { await api(`/api/v1/recycle-bin/${encodeURIComponent(entryId)}/restore`, { method: "POST" }); await loadRecycleBin(); }
    catch (error) { notify(error.message, true); }
  }

  async function purgeRecycleEntry(entryId) {
    try { await api(`/api/v1/recycle-bin/${encodeURIComponent(entryId)}`, { method: "DELETE" }); await loadRecycleBin(); }
    catch (error) { notify(error.message, true); }
  }

  Object.assign(window, {
    loadAutomationSettings, createAutomationTag, deleteAutomationTag, assignAutomationTag,
    createDelayProfile, deleteDelayProfile, toggleImportListUsername, createImportList,
    previewImportList, syncImportList, deleteImportList, loadRecycleBin,
    saveRecycleBinSettings, restoreRecycleEntry, purgeRecycleEntry,
  });

  document.querySelector('[data-settings-tab="automation"]')?.addEventListener("click", loadAutomationSettings);
})();
