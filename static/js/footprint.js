let chipsExpanded = false;   // 足迹默认折叠到两行

const DAY = 86400000;
/* 时间分组的桶界(本地零点起算):今天/最近三天/一周内/更早;无时间的旧条目落"更早" */
function timeBucket(t) {
  const midnight = new Date(); midnight.setHours(0, 0, 0, 0);
  const start = midnight.getTime();
  if (t >= start) return "今天";
  if (t >= start - 2 * DAY) return "最近三天";
  if (t >= start - 6 * DAY) return "一周内";
  return "更早";
}

function renderChips() {
  // 图标瘦成色点 + 即时筛选 + 排序切换:词一多,靠扫是扫不过来的
  const q = (document.getElementById("chip-search").value || "").trim().toLowerCase();
  let words = [...visited.entries()];
  if (historyFilter !== "all") {
    words = words.filter(([, v]) => (v.feats ?? []).includes(historyFilter));
  }
  if (q) {
    words = words.filter(([w]) => w.toLowerCase().includes(q));
  }
  words.sort((a, b) => chipSort === "name"
    ? a[0].localeCompare(b[0], "zh-Hans-CN")
    : (b[1].time || 0) - (a[1].time || 0));
  const dots = feats => ["roam", "deep", "detail"].filter(f => (feats ?? []).includes(f))
    .map(f => `<i class="dot dot-${f}"></i>`).join("");
  const chipHtml = ([w, v]) =>
    `<span class="chip" onclick="goCached('${esc(w).replace(/'/g, "\\'")}')">${esc(w)}${dots(v.feats)}</span>`;
  // 时间排序时按桶分节(找回"昨天那个词"是高频动作);名称排序时平铺,分节没意义
  let html;
  if (chipSort === "time" && words.length) {
    const groups = [];
    for (const item of words) {
      const label = timeBucket(item[1].time || 0);
      (groups[label] ??= []).push(item);
    }
    html = Object.entries(groups).map(([label, items]) =>
      `<div class="chip-sec">${label} · ${items.length}</div>` + items.map(chipHtml).join("")
    ).join("");
  } else {
    html = words.map(chipHtml).join("");
  }
  document.getElementById("chips").innerHTML =
    html || `<span style="color:#6a6f7c;font-size:13px">(没有匹配的足迹)</span>`;
  document.getElementById("chip-count").textContent = ` · ${words.length} 词`;

      const wrap = document.getElementById("chips-wrap");
      const tg = document.getElementById("chips-toggle");
      wrap.classList.toggle("collapsed", !chipsExpanded);
      tg.textContent = chipsExpanded ? "收起 ▴" : "展开全部 ▾";
      // 折叠状态下若内容不足两行,隐藏切换按钮
      requestAnimationFrame(() => {
        tg.hidden = !chipsExpanded && wrap.scrollHeight <= wrap.clientHeight + 4;
      });
    }

    function toggleChips() {
      chipsExpanded = !chipsExpanded;
      renderChips();
    }

    let historyFilter = "all";
    function setFilter(f) {
      historyFilter = f;
      document.querySelectorAll(".ftab:not(.stab)").forEach(t => t.classList.toggle("active", t.dataset.f === f));
      renderChips();
    }

    let chipSort = "time";   // 足迹排序:最近(默认,越新越靠前)/名称(稳定,好扫)
    function setSort(s) {
      chipSort = s;
      document.querySelectorAll(".stab").forEach(t => t.classList.toggle("active", t.dataset.s === s));
      renderChips();
    }

    function roamFromInput() {
      roam(document.getElementById("word-input").value);
    }

    