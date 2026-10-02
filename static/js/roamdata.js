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
      <div class="rw" onclick="goWord('${w}')">${esc(it.word)}</div>
      <div class="rbtns">
        <button class="mini" onclick="roamDeep('${w}')" title="深挖这个词">🔍</button>
        <a class="rb" href="https://search.bilibili.com/all?keyword=${encodeURIComponent(it.word)}" target="_blank" title="去B站搜这个词">B站▶</a>
        <button class="mini" onclick="blacklistWord('${w}')" title="拉黑:以后永不推荐这个词">🚫</button>
      </div>
      <div class="note">${esc(it.note)}</div>
    </div>`;
      };
      box.innerHTML = `<div class="r-toolbar">
      <button id="tree-fill-btn" onclick="fillTreeDetails()" title="给这棵树里所有缺详情的词批量生成 📖 详情">📚 整树补详情</button>
      <span id="tree-fill-progress" class="map-note" title="跑的时候点这里停止"></span>
    </div>
    <div class="r-grid">
    <div><h4>⬆ 上级分类</h4>${(d.parents ?? []).map(mini).join("")}</div>
    <div><h4>⬇ 下级分类</h4>${(d.children ?? []).map(mini).join("")}</div>
    <div><h4>↔ 相邻词</h4>${(d.similar ?? []).map(mini).join("")}</div>
  </div>`;
    }

    /* ===== 📚 整树补详情:拉清单→确认→前端逐个调 /api/expand,可随时停 ===== */
    let treeFillStop = false;
    let treeFillRunning = false;   // 防重入记在模块级:面板重渲染会让按钮上的标记归零,两个循环并跑就重复请求了

    async function fillTreeDetails(deepOnly) {
      const btn = document.getElementById("tree-fill-btn");
      const prog = document.getElementById("tree-fill-progress");
      if (!btn || !prog) return;
      if (treeFillRunning) { prog.textContent = "上一轮还在跑,点进度文字可停止"; return; }
      treeFillRunning = true;
      treeFillStop = false;
      prog.textContent = "拉清单…";
      let list;
      try {
        const resp = await fetch(`/api/tree-words?word=${encodeURIComponent(currentWord)}`);
        list = (await resp.json()).items ?? [];
      } catch (err) {
        prog.textContent = "清单拉取失败:" + (err.message || err);
        treeFillRunning = false;
        return;
      }
      const todo = list.filter(it => !it.has_detail && !it.black && (!deepOnly || it.grp === "deep"));
      if (!todo.length) {
        prog.textContent = deepOnly ? "深挖词的详情都齐了 ✓" : "这棵树的详情都齐了 ✓";
        treeFillRunning = false;
        return;
      }
      if (!confirm(`${deepOnly ? "深挖维度里" : "这棵树共"} ${todo.length} 个词缺详情(整树 ${list.length} 词,其余已有/已拉黑,自动跳过)。\n每条约 1 分钱,预计 1~2 分钟,生成中可点进度文字停止。继续?`)) {
        treeFillRunning = false;
        prog.textContent = "";
        return;
      }
      const flavor = document.getElementById("flavor-input").value;
      const failed = [];
      let done = 0;
      for (const it of todo) {
        if (treeFillStop || !document.getElementById("tree-fill-progress")) break;  // 用户停止/收起面板
        prog.textContent = `${done + 1}/${todo.length}:${it.word}…`;
        try {
          const resp = await fetch(`/api/expand?word=${encodeURIComponent(it.word)}&mode=detail&flavor=${encodeURIComponent(flavor)}`);
          const body = await resp.json();
          if (!resp.ok) throw new Error(body.error || resp.statusText);
          const feats = new Set(visited.get(it.word)?.feats ?? []);
          feats.add("detail");
          visited.set(it.word, { feats: [...feats], time: Date.now() / 1000 });
          prog.textContent = `${++done}/${todo.length} ✓ ${it.word}`;
        } catch (err) {
          failed.push(`${it.word}(${(err.message || err).slice(0, 40)})`);
        }
      }
      renderChips();
      refreshSeen();
      treeFillRunning = false;
      prog.textContent = treeFillStop
        ? `已停止:完成 ${done}/${todo.length}`
        : `完成 ${done}/${todo.length}` + (failed.length ? ` · 失败:${failed.join("、")}` : " · 全部成功 ✓");
    }

    /* 深挖页的 📚:打开漫游结果面板(里面有进度条),只跑深挖维度的词 */
    async function fillFromDeep() {
      const box = document.getElementById("center-roamdata");
      if (box && box.hidden) await roamData();
      fillTreeDetails(true);
    }

    