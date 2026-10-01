/* ===== 💬对话条:绑当前词的多轮追问 =====
       换词自动换对话(内存按词分桶,刷新即清);首轮吃后端 asks 缓存,之后带最近 6 轮上下文 */
    const chatMem = new Map();   // word -> [{role, content}]
    let chatBusy = false;

    function toggleChat() {
      const box = document.getElementById("center-chat");
      if (!box) return;
      if (!box.hidden) { box.hidden = true; return; }
      openChat();
    }

    function openChat(prefill) {
      const box = document.getElementById("center-chat");
      if (!box) return;
      box.hidden = false;
      renderChat();
      if (prefill !== undefined) {
        const inp = document.getElementById("chat-input");
        inp.value = prefill;
        inp.focus();
      }
    }

    function renderChat(loading) {
      const box = document.getElementById("center-chat");
      const hist = chatMem.get(currentWord) ?? [];
      const msgs = hist.map(m =>
        `<div class="chat-m ${m.role === "user" ? "you" : "ai"}">${m.role === "user" ? "你:" : "答:"}${esc(m.content)}</div>`
      ).join("");
      box.innerHTML = `<div class="chat-list" id="chat-list">${msgs ||
        `<div style="color:#6a6f7c">关于「${esc(currentWord)}」随便问,介绍原文我带着当上下文</div>`}</div>
      <input id="chat-input" placeholder="接着问,回车发送" ${loading ? "disabled" : ""}>`;
      const list = document.getElementById("chat-list");
      if (loading) list.insertAdjacentHTML("beforeend", `<div class="chat-m ai">答:想一会儿…</div>`);
      list.scrollTop = list.scrollHeight;
      const inp = document.getElementById("chat-input");
      inp.addEventListener("keydown", e => { if (e.key === "Enter") sendChat(); });
      if (!loading && !chatBusy && hist.length === 0) inp.focus();
    }

    async function sendChat() {
      const inp = document.getElementById("chat-input");
      const q = (inp?.value || "").trim();
      if (!q || chatBusy) return;
      chatBusy = true;   // 只当防重入闸门,不禁用输入框(渲染态只看 loading)
      inp.value = "";
      const hist = chatMem.get(currentWord) ?? [];
      const dbox = document.getElementById("center-detail");
      const ctx = dbox?.dataset?.owner === currentWord && dbox?.dataset?.raw ? dbox.dataset.raw : "";
      renderChat(true);
      let errMsg = "";
      try {
        const resp = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            word: currentWord, q, ctx,
            history: hist.slice(-12).map(m => ({ role: m.role, content: m.content })),  // 最近 6 轮
          }),
        });
        const body = await resp.json();
        if (!resp.ok) throw new Error(body.error || resp.statusText);
        hist.push({ role: "user", content: q }, { role: "assistant", content: body.data.answer });
        chatMem.set(currentWord, hist);
      } catch (err) {
        errMsg = err.message || String(err);
      }
      chatBusy = false;
      renderChat();
      if (errMsg) {   // 问题还回输入框,气泡不算数
        const i2 = document.getElementById("chat-input");
        if (i2) { i2.value = q; i2.focus(); }
        document.getElementById("chat-list")
          .insertAdjacentHTML("beforeend", `<div class="chat-m err">出错:${esc(errMsg)}</div>`);
      }
    }

    