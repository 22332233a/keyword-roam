const roamDataMem = new Map();   // word -> 漫游结果数据(会话内,免得重复请求)

    /* 展开漫游结果盒(手风琴成员)。wantData=true 时把漫游数据交出来,供调用方决定
       要不要自动补详情 —— 这条路上不能只依赖 "盒子已经开着" 就早退,否则和
       renderBasic() 里那句自动展开撞车时,谁先进谁拿数据,另一个就扑空了。 */
    /* 展开漫游结果盒(手风琴成员)。
       roam.js 会用 openRoamData(true, 本次漫游数据):这一次漫游刚拿到的数据直接给它渲染,
       不再让 roamData() 去重拉一遍 —— 重入会互相把盒子"开了又关",返回值也就丢了
       (2026-10-04 的 bug:自动补详情因此被整个跳过)。
       renderBasic/renderDeep 那句不带参数:只是"顺手把盒子露出来",数据由 roamData() 自己拉。 */
    async function openRoamData(wantData, data) {
      const box = document.getElementById("center-roamdata");
      if (!box) return undefined;
      if (data) {
        roamDataMem.set(currentWord, data);
        if (box.hidden) { closeCenterBoxes("center-roamdata"); box.hidden = false; }
        renderRoamData(box, data);
        return data;
      }
      if (!box.hidden) {
        // 盒子已经开着:要数据就从会话缓存里取(没有就等它拉完)
        if (!wantData) return undefined;
        if (roamDataMem.has(currentWord)) return roamDataMem.get(currentWord);
        await roamData();
        return roamDataMem.get(currentWord);
      }
      return await roamData();
    }

    /* 返回:
         body.data —— 这次真的新拉了漫游数据(调用方据此决定要不要自动补详情)
         undefined —— 只是开合/重画已有的盒子(不该触发任何花钱的动作) */
    async function roamData() {
      const box = document.getElementById("center-roamdata");
      if (!box) return;
      if (!box.hidden) { box.hidden = true; return; }   // 开着 → 收起
      closeCenterBoxes("center-roamdata");
      box.hidden = false;
      const mem = roamDataMem.get(currentWord);
      // 命中会话缓存(比如刚刚渲染过)也要把数据交出去——自动补详情的判断靠这个返回值,
      // 漏了这条 return,就会"先点过一次漫游结果 → 再漫游同一个词 → 不再补详情"。
      if (mem) { renderRoamData(box, mem); return mem; }   // 每次展开都重画,足迹变色保持新鲜
      box.textContent = "读漫游缓存…";
      try {
        const flavor = document.getElementById("flavor-input").value;
        const resp = await fetch(`/api/expand?word=${encodeURIComponent(currentWord)}&flavor=${encodeURIComponent(flavor)}&mode=basic&cache_only=1`);
        const body = await resp.json();
        if (!resp.ok) {
          // 没有漫游树时,后端会把"有没有深挖"一起告诉我们:有深挖就仍然给补详情的入口
          renderRoamEmpty(box, !!body.has_deep);
          return;
        }
        roamDataMem.set(currentWord, body.data);
        renderRoamData(box, body.data);
        return body.data;
      } catch (err) {
        renderRoamEmpty(box, false);
      }
    }

    /* 没有漫游树时的空态:一句解释 + 一个出口。
       hasDeep 为真说明这个词有深挖树,左栏那些维度里的词照样可以一键补详情。 */
    function renderRoamEmpty(box, hasDeep) {
      const w = esc(currentWord).replace(/'/g, "\\'");
      const deepLink = hasDeep
        ? `<a class="regen-link" onclick="fillTreeDetails(true)" title="把左栏深挖维度里还缺详情的词批量补上">🔍补深挖词详情</a>`
        : "";
      box.innerHTML = `${deepLink ? `<div class="r-toolbar">${deepLink}</div>` : ""}
    <div class="r-empty">
      <div class="map-note">这个词还没有漫游树(只有深挖,或者还没漫游过),所以没有上级/下级/相邻可看。${hasDeep ? "左栏的深挖维度可以照常看,缺详情也能一键补。" : ""}</div>
      <button class="deep-btn" onclick="roam('${w}')">🧭 漫游一次这个词</button>
    </div>`;
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
      // 深挖维度不在这里展示(左栏词卡已接管),本盒只管漫游三组 + 补详情工具栏。
      // 两条补详情路各管一片,谁有活干谁才出现:
      //   📚 整树补详情  = 漫游树的上级/下级/相邻  → 得有漫游树
      //   🔍 补深挖词详情 = 左栏那些深挖维度里的词  → 得有深挖树
      // 但"只有深挖、没有漫游树"的词根本走不到这里(上面拉缓存失败就转 renderRoamEmpty 了),
      // 所以这个函数只可能处理有漫游树的词:整树按钮必有,深挖按钮看它有没有深挖树。
      const hasDeep = (((d.deep || {}).dimensions) || []).length > 0;
      const deepLink = hasDeep
        ? `<a class="regen-link" onclick="fillTreeDetails(true)" title="把左栏深挖维度里还缺详情的词批量补上">🔍补深挖词详情</a>`
        : "";
      box.innerHTML = `<div class="r-toolbar">
      <button id="tree-fill-btn" onclick="fillTreeDetails()" title="给这棵树里所有缺详情的词批量生成 📖 详情">📚 整树补详情</button>
      ${deepLink}
      <span id="tree-fill-progress" class="map-note" title="跑的时候点这里停止"></span>
    </div>
    <div class="r-grid">
    <div><h4>⬆ 上级分类</h4>${(d.parents ?? []).map(mini).join("")}</div>
    <div><h4>⬇ 下级分类</h4>${(d.children ?? []).map(mini).join("")}</div>
    <div><h4>↔ 相邻词</h4>${(d.similar ?? []).map(mini).join("")}</div>
  </div>`;
      // 渲染完就把「下级/相邻」排进后台补详情队列(档位在 ⚙设置 → 自动补详情)
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
      const todo = list.filter(it => !it.has_detail && !it.black && !it.skipped && (!deepOnly || it.grp === "deep"));
      const held = list.filter(it => it.skipped && !it.black).length;
      if (!todo.length) {
        prog.textContent = (deepOnly ? "深挖词的详情都齐了 ✓" : "这棵树的详情都齐了 ✓")
          + (held ? `(另有 ${held} 个词反复生成失败,已跳过——可在漫游结果里点「失败 N,点这里重试」强跑)` : "");
        treeFillRunning = false;
        return;
      }
      if (!confirm(`${deepOnly ? "深挖维度里" : "这棵树共"} ${todo.length} 个词缺详情(整树 ${list.length} 词,其余已有/已拉黑/反复失败已跳过,自动跳过)。\n每条约 1 分钱,预计 1~2 分钟,生成中可点进度文字停止。继续?`)) {
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

    