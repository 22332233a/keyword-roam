/* ===== 左栏:📝笔记(上) + 按分类分组的词列表(下) =====
       词卡点词=跟随当前模式,🔍=深挖,📖=右栏看详情;足迹变化由 refreshSeen 同步"去过"色 */
    function sideItem(it, id) {
      const seen = visited.has(it.word) ? " seen" : "";
      const w = esc(it.word).replace(/'/g, "\\'");
      return `<div class="s-item${seen}" id="${id}" data-word="${esc(it.word)}">
    <div class="row">
      <span class="w" onclick="goWord('${w}')" title="${esc(it.note)}">${esc(it.word)}</span>
      <button class="mini" onclick="roamDeep('${w}')" title="深挖这个词">🔍</button>
      <button class="mini" onclick="sideDetail('${w}')" title="看这个词的详情">📖</button>
    </div>
    <div class="note">${esc(it.note)}</div>
  </div>`;
    }

    /* 渲染所有分组:左栏出词条卡片;右侧文字目录只在笔记列收起时显示(词+分类速查) */
    function renderGroups(groups) {
      let side = "", toc = "";
      groups.forEach((g, gi) => {
        side += `<div class="s-group" id="v${gi}h"><h3>${esc(g.title)}</h3>` +
          (g.items ?? []).map((it, i) => sideItem(it, `v${gi}-${i}`)).join("") + `</div>`;
        toc += `<div class="toc-g"><div class="toc-t" onclick="jumpTo('v${gi}h')">${esc(g.title)}</div>` +
          (g.items ?? []).map((it, i) =>
            `<span class="toc-w" onclick="jumpTo('v${gi}-${i}')" title="${esc(it.note)}">${esc(it.word)}</span>`
          ).join("") + `</div>`;
      });
      document.getElementById("side-groups").innerHTML = side;
      const tocEl = document.getElementById("toc");
      if (tocEl) tocEl.innerHTML = toc;
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

    /* 足迹变化后同步"去过"变色,不重建列表(避免滚动位置跳动) */
    function refreshSeen() {
      document.querySelectorAll(".s-item").forEach(el => {
        el.classList.toggle("seen", visited.has(el.dataset.word));
      });
    }
