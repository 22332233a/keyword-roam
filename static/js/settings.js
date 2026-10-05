/* ===== ⚙设置面板:口味预设/详情长度/放飞程度,存 data/settings.json,即点即存即生效 ===== */
const BUILTIN_FLAVORS = [
  "半学习半娱乐,科技/商业/历史/人文乱炖,别太正经",
  "越离谱越好,专挑冷门猎奇的",
  "只看历史向,越老越好",
  "硬核技术流,别怕深",
  "吃货视角,万物皆可吃",
  "悬疑侦探向,多讲事故和内幕",
];

let setDraft = { detail_len: "标准", temp_style: "标准", flavors: [], blacklist: [],
                 api: { base_url: "", model: "", temperature: "", max_tokens: "", has_key: false, key_preview: "" } };
let apiDraftObj = { base_url: "", key: "", model: "", temperature: "", max_tokens: "" };
let apiKeyTouched = false;   // 用户是否动过 key 输入框(动过才提交,避免误清)

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
  if (!Array.isArray(setDraft.blacklist)) setDraft.blacklist = [];
  setSegActive("seg-detail-len", setDraft.detail_len);
  setSegActive("seg-temp", setDraft.temp_style);
  setSegActive("seg-auto-detail", setDraft.auto_detail || "smart");
  renderFlavorChips();
  renderBlChips();
  renderApiFields();
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

/* 自动补详情档位:off 关 / smart 只补下级+相邻 / all 连上级也补 */
function setAutoDetail(el) {
  setSegActive("seg-auto-detail", el.dataset.v);
  setDraft.auto_detail = el.dataset.v;
  saveSettings({ auto_detail: el.dataset.v });
}

/* ===== 黑名单:永不推荐的词;卡片 🚫 一键拉黑也走这里 ===== */
function renderBlChips() {
  const wrap = document.getElementById("bl-chips");
  if (!wrap) return;
  wrap.innerHTML = (setDraft.blacklist || []).map(w =>
    `<span class="chip fchip" title="点 × 解禁">${esc(w)}<span class="fx" data-v="${esc(w)}" onclick="delBlacklist(this.dataset.v)">×</span></span>`
  ).join("") || `<span style="color:#6a6f7c">还没有拉黑的词</span>`;
}

async function addBlacklist() {
  const inp = document.getElementById("bl-new");
  const w = (inp?.value || "").trim().slice(0, 30);
  if (!w) return;
  await pushBlacklist(w);
  if (inp) inp.value = "";
}

async function blacklistWord(w) {
  const added = await pushBlacklist(w);
  const st = document.getElementById("status");
  if (st) {
    st.textContent = added ? `已拉黑「${w}」,以后不会再推荐它` : `「${w}」已经在黑名单里了`;
    setTimeout(() => st.textContent = "", 2500);
  }
}

async function pushBlacklist(w) {
  const added = !setDraft.blacklist.includes(w);
  if (added) setDraft.blacklist.push(w);
  renderBlChips();
  await saveSettings({ blacklist: setDraft.blacklist });
  return added;
}

function delBlacklist(w) {
  setDraft.blacklist = setDraft.blacklist.filter(x => x !== w);
  renderBlChips();
  saveSettings({ blacklist: setDraft.blacklist });
}

/* ===== 模型接口:端点/key/模型。存 settings.api,留空即回落环境变量 ===== */

/* 把草稿铺到表单上。key 输入框永远留空 —— 后端只回 has_key + 掩码预览,不回原文 */
function renderApiFields() {
  const a = setDraft.api || {};
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v || ""; };
  set("api-base", a.base_url);
  set("api-model", a.model);
  set("api-max-tokens", a.max_tokens);
  set("api-temperature", a.temperature);
  const k = document.getElementById("api-key");
  if (k) k.value = "";
  apiKeyTouched = false;
  apiDraftObj = { base_url: a.base_url || "", key: "", model: a.model || "",
                  temperature: a.temperature || "", max_tokens: a.max_tokens || "" };
  const note = document.getElementById("api-key-note");
  if (note) {
    note.textContent = a.has_key
      ? `已保存:${a.key_preview}(留空即不改动)`
      : "未保存 key —— 会回落到环境变量;若也没有,生成时会报错";
  }
}

/* 输入即存(沿用面板"即点即存"的风格),600ms 防抖避免打字打一半就落盘 */
let apiSaveTimer = null;
function apiDraft(field, value) {
  apiDraftObj[field] = value;
  if (field === "key") apiKeyTouched = true;
  clearTimeout(apiSaveTimer);
  apiSaveTimer = setTimeout(() => saveApiDraft(), 600);
}

async function saveApiDraft() {
  const prev = (setDraft.api || {}).key_preview || "";
  const selected = (document.getElementById("api-model") || {}).value || "";
  const hasPrev = !!(setDraft.api || {}).has_key;
  await saveSettings({ api: apiDraftObj });
  // saveSettings 会把服务端返回(已掩码)的整份设置写回 setDraft,
  // 这样掩码预览和 has_key 都保持最新;但 key 输入框要清掉,免得明文停在页面上
  const k = document.getElementById("api-key");
  if (k && apiKeyTouched) k.value = "";
  apiKeyTouched = false;
  if (selected) {                            // 从下拉里选过模型 → 补一次保存
    const a = setDraft.api || {};
    if (a.model !== selected) saveSettings({ api: { model: selected } });
  }
  const note = document.getElementById("api-key-note");
  if (note) {
    const a = setDraft.api || {};
    note.textContent = a.has_key
      ? `已保存:${a.key_preview}(留空即不改动)`
      : (prev ? "已清除保存的 key" : "未保存 key —— 会回落到环境变量;若也没有,生成时会报错");
  }
}

/* 清除已保存的 key(哨兵值让后端区分"清空"和"别动") */
async function clearApiKey() {
  apiKeyTouched = false;
  const k = document.getElementById("api-key");
  if (k) k.value = "";
  delete apiDraftObj.key;
  apiDraftObj.key = "__CLEAR__";
  await saveApiDraft();
  renderApiFields();
}

/* 连接测试:服务端代打,所以它失败=端点/key/网络问题;
   若这里通了而浏览器直连不通,那就是 CORS —— 结果里会给这句提示 */
const API_REASON_CLASS = {
  missing_key: "warn", tls: "bad", connection: "bad", timeout: "bad",
  auth: "bad", forbidden: "bad", not_found: "bad", rate_limit: "warn", server: "warn",
};

async function testConn() {
  const box = document.getElementById("api-result");
  const btn = document.getElementById("api-test-btn");
  if (!box) return;
  box.hidden = false;
  box.className = "api-result pending";
  box.textContent = "测试中…(先打 /models 拉模型列表)";
  if (btn) { btn.disabled = true; }
  let r;
  try {
    const resp = await fetch("/api/test-conn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api: apiDraftObj }),
    });
    r = await resp.json();
    if (!resp.ok) throw new Error(r.error || resp.statusText);
  } catch (err) {
    box.className = "api-result bad";
    box.textContent = "测试请求本身失败:" + (err.message || err);
    if (btn) btn.disabled = false;
    return;
  }
  if (btn) btn.disabled = false;
  renderApiResult(r);
}

function renderApiResult(r) {
  const box = document.getElementById("api-result");
  if (!box) return;
  const cls = r.ok ? "ok" : (API_REASON_CLASS[r.reason] || "bad");
  box.className = "api-result " + cls;
  const lines = [];
  lines.push(`端点 ${r.base_url}`);
  lines.push(`模型 ${r.model || "(未设)"}   max_tokens ${r.max_tokens}`);
  lines.push(`key 来源:${({ settings: "⚙设置", env: "环境变量", none: "无" })[r.key_from] || r.key_from}`);
  if (r.ok) {
    lines.push(`✓ 连通,${r.latency_ms}ms,拿到 ${r.models.length} 个模型`);
    if (r.model_listed === true) lines.push(`✓ 模型名在列表里`);
    else if (r.model_listed === false) {
      lines.push(`⚠ 模型名不在列表里 —— 端点是通的,但这个名字可能打不通。候选:`);
      lines.push("   " + r.models.slice(0, 12).join("、"));
    }
  } else {
    lines.push(`✗ 失败:${r.hint || r.reason}${r.status_code ? `(HTTP ${r.status_code})` : ""}`);
    if (r.raw_error) lines.push(`原始信息:${r.raw_error.slice(0, 200)}`);
  }
  box.innerHTML = "";
  lines.forEach((t, i) => {
    const d = document.createElement("div");
    if (i === 0 && !r.ok) d.className = "api-err";
    d.textContent = t;
    box.appendChild(d);
  });
  const h = document.createElement("div");
  h.className = "api-hint";
  h.textContent = r.ok ? r.browser_hint : "修好上面这条再点一次「测试连接」。";
  box.appendChild(h);
  if (r.ok && r.models && r.models.length) fillModelList(r.models);
}

function fillModelList(models) {
  const dl = document.getElementById("api-model-list");
  if (!dl) return;
  dl.innerHTML = "";
  models.slice(0, 200).forEach(m => {
    const o = document.createElement("option");
    o.value = m;
    dl.appendChild(o);
  });
}
