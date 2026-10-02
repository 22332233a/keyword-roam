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
      ${hist.length >= 2 && !loading ? `<div class="chat-regen" onclick="regenChat()" title="删掉最后一轮,重新生成回答">🔄 重新回答</div>` : ""}
      <input id="chat-input" placeholder="接着问,回车发送" ${loading ? "disabled" : ""}>`;
      const list = document.getElementById("chat-list");
      if (loading) list.insertAdjacentHTML("beforeend", `<div class="chat-m ai">答:想一会儿…</div>`);
      list.scrollTop = list.scrollHeight;
      const inp = document.getElementById("chat-input");
      inp.addEventListener("keydown", e => { if (e.key === "Enter") sendChat(); });
      if (!loading && !chatBusy && hist.length === 0) inp.focus();
    }

    async function sendChat(qOverride, regen) {
      const inp = document.getElementById("chat-input");
      const q = ((qOverride ?? inp?.value) || "").trim();
      if (!q || chatBusy) return;
      chatBusy = true;   // 只当防重入闸门,不禁用输入框(渲染态只看 loading)
      if (!qOverride && inp) inp.value = "";
      const hist = chatMem.get(currentWord) ?? [];
      const dbox = document.getElementById("center-detail");
      let ctx = "";
      if (dbox?.dataset?.raw) {
        const owner = dbox.dataset.owner || "";
        ctx = owner && owner !== currentWord
          ? `（注意:这段原文属于「${owner}」,不是中心词「${currentWord}」的）\n${dbox.dataset.raw}`
          : dbox.dataset.raw;   // 划词追问常落在别的词的详情卡上,原文带不带归属,模型才不会装看不见
      }
      renderChat(true);
      let errMsg = "";
      try {
        const resp = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            word: currentWord, q, ctx, regen: !!regen,
            history: hist.slice(-12).map(m => ({ role: m.role, content: m.content })),  // 最近 6 轮
          }),
        });
        const body = await resp.json();
        if (!resp.ok) throw new Error(body.error || resp.statusText);
        hist.push({ role: "user", content: q }, { role: "assistant", content: body.data.answer });
        chatMem.set(currentWord, hist);
      } catch (err) {
        errMsg = err.message || String(err);
        if (regen) {   // 重答失败:至少把问题留回记录,别让刚才删掉的一轮真消失
          hist.push({ role: "user", content: q });
          chatMem.set(currentWord, hist);
        }
      }
      chatBusy = false;
      renderChat();
      if (errMsg) {   // 正常发送:问题还回输入框,气泡不算数
        if (!regen && inp) { inp.value = q; inp.focus(); }
        document.getElementById("chat-list")
          .insertAdjacentHTML("beforeend", `<div class="chat-m err">出错:${esc(errMsg)}</div>`);
      }
    }

    /* 🔄 重新回答:删掉最后一轮问答,带同样的问题和上下文再来一次(regen 跳过 asks 缓存) */
    function regenChat() {
      if (chatBusy) return;
      const hist = chatMem.get(currentWord) ?? [];
      if (hist.length < 2 || hist[hist.length - 1].role !== "assistant") return;
      const q = hist[hist.length - 2].content;
      chatMem.set(currentWord, hist.slice(0, -2));
      renderChat();
      sendChat(q, true);
    }

    