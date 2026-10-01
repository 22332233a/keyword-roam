/* ===== 左栏:按分类分组的词列表,点词=跟随当前模式,📖=右栏看它的详情 ===== */
    function sideItem(it, id) {
      const seen = visited.has(it.word) ? " seen" : "";
      const w = esc(it.word).replace(/'/g, "\\'");
      return `<div class="s-item${seen}" id="${id}" data-word="${esc(it.word)}">
    <div class="row">
      <span class="w" onclick="goWord('${w}')" title="${esc(it.note)}">${esc(it.word)}</span>
      <button class="mini" onclick="roamDeep('${w}')" title="深挖这个词">🔍</button>
      <button class="mini" onclick="sideDetail('${w}')" title="在右栏看这个词的详情">📖</button>
    </div>
    <div class="note">${esc(it.note)}</div>
  </div>`;
    }

    /* 渲染所有分组:左栏出词条卡片,右栏出纯文字目录(点击跳到左栏对应位置) */
    function renderGroups(groups) {
      const base = "v";   // 每个词条的锚点 id,目录跳转用
      let side = "", toc = "";
      groups.forEach((g, gi) => {
        const pre = base + gi + "-";
        side += `<div class="s-group" id="${pre}h"><h3>${esc(g.title)}</h3>` +
          (g.items ?? []).map((it, i) => sideItem(it, pre + i)).join("") + `</div>`;
        toc += `<div class="toc-g"><div class="toc-t" onclick="jumpTo('${pre}h')">${esc(g.title)}</div>` +
          (g.items ?? []).map((it, i) =>
            `<span class="toc-w" onclick="jumpTo('${pre}${i}')" title="${esc(it.note)}">${esc(it.word)}</span>`
          ).join("") + `</div>`;
      });
      document.getElementById("sidebar").innerHTML = side;
      document.getElementById("toc").innerHTML = toc;
    }

    /* 目录跳转:左栏滚到对应词条,词条高亮闪一下(组标题只滚动不闪) */
    function jumpTo(id) {
      const el = document.getElementById(id);
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
      if (el.classList.contains("s-item")) {
        el.classList.add("flash");
        setTimeout(() => el.classList.remove("flash"), 1500);
      }
    }

    /* 足迹变化后同步左栏的"去过"变色,不重建列表(避免滚动位置跳动) */
    function refreshSeen() {
      document.querySelectorAll(".s-item").forEach(el => {
        el.classList.toggle("seen", visited.has(el.dataset.word));
      });
    }

    