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

    /* 渲染所有分组:左栏笔记下方出词条卡片(右栏目录已退役) */
    function renderGroups(groups) {
      let side = "";
      groups.forEach((g, gi) => {
        side += `<div class="s-group" id="v${gi}h"><h3>${esc(g.title)}</h3>` +
          (g.items ?? []).map((it, i) => sideItem(it, `v${gi}-${i}`)).join("") + `</div>`;
      });
      document.getElementById("side-groups").innerHTML = side;
    }

    /* 足迹变化后同步"去过"变色,不重建列表(避免滚动位置跳动) */
    function refreshSeen() {
      document.querySelectorAll(".s-item").forEach(el => {
        el.classList.toggle("seen", visited.has(el.dataset.word));
      });
    }
