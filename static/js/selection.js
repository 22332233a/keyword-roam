/* ===== 划词快问:在详情文字里选中词,弹出迷你菜单 ===== */
    const selMenu = document.getElementById("sel-menu");
    let selTerm = "";
    let selContext = "";

    document.addEventListener("mouseup", e => {
      if (selMenu.contains(e.target)) return;   // 菜单内部点击不处理
      setTimeout(() => {
        const sel = window.getSelection();
        const text = sel ? String(sel).trim() : "";
        const box = sel?.anchorNode?.parentElement?.closest(".detail-box");
        if (!box || sel.isCollapsed || text.length < 2 || text.length > 30) {
          selMenu.hidden = true;
          return;
        }
        selTerm = text;
        selContext = box.textContent.trim().slice(0, 500);   // 详情原文当追问上下文
        document.getElementById("sel-term").textContent = `「${text}」`;
        document.getElementById("sel-ans").textContent = "";
        document.getElementById("sel-actions").hidden = false;
        const rect = sel.getRangeAt(0).getBoundingClientRect();
        selMenu.style.top = rect.bottom + window.scrollY + 8 + "px";
        selMenu.style.left = Math.max(8, rect.left + window.scrollX) + "px";
        selMenu.hidden = false;
      }, 0);
    });

    function hideSel() {
      selMenu.hidden = true;
      window.getSelection()?.removeAllRanges();
    }

    /* "是什么?"——选中的词直接走现成的详情模式,零新增后端 */
    async function askWhat() {
      const ans = document.getElementById("sel-ans");
      ans.textContent = "查询中…";
      document.getElementById("sel-actions").hidden = true;
      try {
        const flavor = document.getElementById("flavor-input").value;
        const resp = await fetch(`/api/expand?word=${encodeURIComponent(selTerm)}&mode=detail&flavor=${encodeURIComponent(flavor)}`);
        const body = await resp.json();
        if (!resp.ok) throw new Error(body.error || body.statusText);
        ans.textContent = body.data.detail;
        const fe = new Set(visited.get(selTerm)?.feats ?? []);
        fe.add("detail");
        visited.set(selTerm, { feats: [...fe], time: Date.now() / 1000 });
        renderChips();
      } catch (err) {
        ans.textContent = "出错:" + err.message;
      }
    }

    /* "追问…"——就地展开底部对话条并预填,划词追问与对话条合流(原浮窗单发版退役) */
    function showAskInput() {
      const term = selTerm;
      hideSel();
      openChat(`「${term}」`);
    }

    