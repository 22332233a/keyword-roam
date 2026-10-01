const roamDataMem = new Map();   // word -> 漫游结果数据(会话内,免得重复请求)

    async function roamData() {
      const box = document.getElementById("center-roamdata");
      if (!box) return;
      if (!box.hidden) { box.hidden = true; return; }   // 开着 → 收起
      box.hidden = false;
      const mem = roamDataMem.get(currentWord);
      if (mem) { renderRoamData(box, mem); return; }    // 每次展开都重画,足迹变色保持新鲜
      box.textContent = "读漫游缓存…";
      try {
        const flavor = document.getElementById("flavor-input").value;
        const resp = await fetch(`/api/expand?word=${encodeURIComponent(currentWord)}&flavor=${encodeURIComponent(flavor)}&mode=basic&cache_only=1`);
        const body = await resp.json();
        if (!resp.ok) throw new Error(body.error || "还没漫游过这个词");
        roamDataMem.set(currentWord, body.data);
        renderRoamData(box, body.data);
      } catch (err) {
        box.textContent = "(还没有可复用的漫游结果:" + (err.message || "没漫游过") + ")";
      }
    }

    function renderRoamData(box, d) {
      const mini = it => {
        const seen = visited.has(it.word) ? " seen" : "";
        const w = esc(it.word).replace(/'/g, "\\'");
        return `<div class="r-item${seen}">
      <div class="rrow">
        <span class="rw" onclick="goWord('${w}')">${esc(it.word)}</span>
        <button class="mini" onclick="roamDeep('${w}')" title="深挖这个词">🔍</button>
        <a class="rb" href="https://search.bilibili.com/all?keyword=${encodeURIComponent(it.word)}" target="_blank" title="去B站搜这个词">B站▶</a>
      </div>
      <div class="note">${esc(it.note)}</div>
    </div>`;
      };
      box.innerHTML = `<div class="r-grid">
    <div><h4>⬆ 上级分类</h4>${(d.parents ?? []).map(mini).join("")}</div>
    <div><h4>⬇ 下级分类</h4>${(d.children ?? []).map(mini).join("")}</div>
    <div><h4>↔ 相邻词</h4>${(d.similar ?? []).map(mini).join("")}</div>
  </div>`;
    }

    