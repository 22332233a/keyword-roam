async function roam(word) { await go(word, "basic"); }
    async function roamDeep(word) { await go(word, "deep"); }
    /* 🎲单词重掷:无视缓存重新生成当前页模式的词;详情另有 🔄重写,黑名单在设置面板 */
    async function rerollWord() { await go(currentWord, currentViewMode, true); }
    /* 按当前页面模式打开一个词:深挖页里点击=深挖,漫游页里点击=漫游 */
    function goWord(word) { go(word, currentViewMode); }

    /* 足迹点击:优先吃缓存——词有什么数据就开什么(分类筛选激活且词有对应数据时按分类跳,
       否则按 深挖>漫游>详情 的富度优先),什么都没有才按当前页面模式去生成 */
    function goCached(word) {
      const feats = visited.get(word)?.feats ?? [];
      const f = historyFilter !== "all" && feats.includes(historyFilter) ? historyFilter
        : feats.includes("deep") ? "deep"
        : feats.includes("roam") ? "roam"
        : feats.includes("detail") ? "detail" : "";
      if (f === "detail") { showDetail(word, false); return; }   // 详情不换页,右栏直接出解释
      if (f) { go(word, f === "roam" ? "basic" : f); return; }
      goWord(word);
    }

    async function go(word, mode, force) {
      word = (word || "").trim();
      if (!word) return;
      currentWord = word;
      document.getElementById("word-input").value = word;
      const status = document.getElementById("status");
      status.textContent = (force ? "重掷中…(清掉旧缓存重新生成)" : mode === "deep" ? "深挖中…(思维链模型,多等几秒)" : "问 AI 中…");
      status.className = "";

      try {
        const flavor = document.getElementById("flavor-input").value;
        const resp = await fetch(`/api/expand?word=${encodeURIComponent(word)}&flavor=${encodeURIComponent(flavor)}&mode=${mode}${force ? "&force=1" : ""}`);
        const body = await resp.json();
        if (!resp.ok) throw new Error(body.error || body.statusText);

        const d = body.data;
        // 更新足迹:叠加功能标记,挪到最新位置
        const feats = new Set(visited.get(word)?.feats ?? []);
        feats.add(mode === "basic" ? "roam" : mode);
        visited.set(word, { feats: [...feats], time: Date.now() / 1000 });
        if (mode === "basic") renderBasic(d, body.cached);
        else renderDeep(d, body.cached);
        renderChips();
        refreshSeen();
        status.textContent = "";
      } catch (err) {
        status.textContent = "出错:" + err.message;
        status.className = "error";
      }
    }

    function renderCenter(word, tag) {
      const w = esc(word).replace(/'/g, "\\'");
      document.getElementById("center").innerHTML =
        `${esc(word)}
     <small>${tag}<br>${links(word)}</small>
     <div class="center-actions">
       <button class="deep-btn lg" onclick="roamDeep('${w}')">🔍深挖</button>
       <button class="deep-btn lg" onclick="toggleDetail('${w}')">📖详情</button>
       <button class="deep-btn lg" onclick="roamData()">🧭漫游结果</button>
       <button class="deep-btn lg" onclick="toggleChat()">💬对话</button>
       <button class="deep-btn lg" onclick="toggleNote()">📝笔记</button>
       <button class="deep-btn lg" onclick="rerollWord()" title="清掉这个词当前页模式(漫游/深挖)的缓存,花钱重新生成">🎲重掷</button>
     </div>
     <div class="detail-box" id="center-detail" hidden></div>
     <div class="detail-box think-box" id="center-think" hidden></div>
     <div class="detail-box" id="center-roamdata" hidden></div>
     <div class="detail-box chat-box" id="center-chat" hidden></div>
     <div class="detail-box note-box" id="center-note" hidden></div>`;
    }

    /* 普通漫游:左栏固定三组 */
    function renderBasic(d, cached) {
      currentViewMode = "basic";
      currentThinking = "";
      renderCenter(d.word, (cached ? "✓ 漫游过,读的缓存" : "✨ 新大陆"));
      renderGroups([
        { title: "⬆ 上级分类", items: d.parents },
        { title: "⬇ 下级分类", items: d.children },
        { title: "↔ 相邻词(点词继续漫游)", items: d.similar },
      ]);
    }

    /* 深挖:按类型动态生成的维度进左栏,🧠思考过程在右栏 */
    let currentThinking = "";

    function renderDeep(d, cached) {
      currentViewMode = "deep";
      currentThinking = d.thinking || "";
      const tag = `[${esc(d.type ?? "?")}] ${esc(d.summary ?? "")}${cached ? " · ✓缓存" : " · ✨"}`;
      renderCenter(d.word, tag);
      if (currentThinking) {
        document.querySelector("#center .center-actions").innerHTML +=
          `<button class="deep-btn lg" onclick="toggleThinking()">🧠思考过程</button>` +
          `<button class="deep-btn lg" onclick="fillFromDeep()" title="批量给这棵树深挖维度里的词生成详情">📚深挖词补详情</button>`;
      }
      renderGroups(
        (d.dimensions ?? []).map(dim => ({ title: "◈ " + (dim.name ?? ""), items: dim.items }))
      );
    }

    function toggleThinking() {
      const box = document.getElementById("center-think");
      if (!box) return;
      if (!box.hidden) { box.hidden = true; return; }
      box.textContent = currentThinking || "(本次没有记录到思考过程)";
      box.hidden = false;
    }

    /* 🧭漫游结果:读这个词已有的漫游数据(上级/下级/相邻词),折叠显示在正下方。
       纯复用——cache_only 模式只查缓存不生成;没漫游过就明说,不花一次钱。
       词可点击,跟随当前页面模式跳转 */
    