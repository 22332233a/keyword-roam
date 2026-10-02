/* ===== ⚙设置面板:口味预设/详情长度/放飞程度,存 data/settings.json,即点即存即生效 ===== */
const BUILTIN_FLAVORS = [
  "半学习半娱乐,科技/商业/历史/人文乱炖,别太正经",
  "越离谱越好,专挑冷门猎奇的",
  "只看历史向,越老越好",
  "硬核技术流,别怕深",
  "吃货视角,万物皆可吃",
  "悬疑侦探向,多讲事故和内幕",
];

let setDraft = { detail_len: "标准", temp_style: "标准", flavors: [] };

function setSegActive(segId, val) {
  document.querySelectorAll(`#${segId} span`)
    .forEach(s => s.classList.toggle("active", s.dataset.v === val));
}

async function openSettings() {
  const box = document.getElementById("settings-view");
  if (!box) return;
  box.hidden = false;
  try {
    const resp = await fetch("/api/settings");
    if (resp.ok) setDraft = await resp.json();
  } catch { /* 拉不到就用草稿默认,面板照常打开 */ }
  if (!Array.isArray(setDraft.flavors)) setDraft.flavors = [];
  setSegActive("seg-detail-len", setDraft.detail_len);
  setSegActive("seg-temp", setDraft.temp_style);
  renderFlavorChips();
}

function closeSettings() {
  const box = document.getElementById("settings-view");
  if (box) box.hidden = true;
}

function renderFlavorChips() {
  const wrap = document.getElementById("flavor-chips");
  if (!wrap) return;
  const mine = setDraft.flavors || [];
  const all = [...new Set([...BUILTIN_FLAVORS, ...mine])];
  wrap.innerHTML = all.map(f => {
    const v = esc(f);
    const x = mine.includes(f)
      ? `<span class="fx" data-v="${v}" onclick="event.stopPropagation();delFlavorPreset(this.dataset.v)" title="删除预设">×</span>`
      : "";
    return `<span class="chip fchip" data-v="${v}" onclick="applyFlavor(this.dataset.v)" title="填进漫游框">${esc(f)}${x}</span>`;
  }).join("");
}

async function saveSettings(patch) {
  const m = document.getElementById("settings-msg");
  try {
    const resp = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    const body = await resp.json();
    if (!resp.ok) throw new Error(body.error || resp.statusText);
    setDraft = body;
    if (m) { m.textContent = "已保存 ✓"; setTimeout(() => m.textContent = "", 1500); }
  } catch (err) {
    if (m) m.textContent = "保存失败:" + (err.message || err);
  }
}

function applyFlavor(v) {
  const inp = document.getElementById("flavor-input");
  if (inp) inp.value = v;
  closeSettings();
}

function addFlavorPreset() {
  const inp = document.getElementById("flavor-new");
  const v = (inp?.value || "").trim().slice(0, 60);
  if (!v) return;
  if (!setDraft.flavors.includes(v)) setDraft.flavors.push(v);
  inp.value = "";
  renderFlavorChips();
  saveSettings({ flavors: setDraft.flavors });
}

function delFlavorPreset(v) {
  setDraft.flavors = setDraft.flavors.filter(f => f !== v);
  renderFlavorChips();
  saveSettings({ flavors: setDraft.flavors });
}

function setDetailLen(el) {
  setSegActive("seg-detail-len", el.dataset.v);
  saveSettings({ detail_len: el.dataset.v });
}

function setTempStyle(el) {
  setSegActive("seg-temp", el.dataset.v);
  saveSettings({ temp_style: el.dataset.v });
}
