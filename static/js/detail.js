/* ===== 右栏:中心词 + 动作按钮 + 共用的详情/思考框 ===== */

    function renderDetailInto(box, word, data) {
      // 右栏详情框是所有词共用的,开头必须标明这段解释是谁的(中心词自己的不标,免得跟大标题重复);
      // 模型可能推断出输入实际指向的名称(如句子→领英中国),一并展示;末尾挂🔄重写入口
      const named = data.word && data.word !== word ? ` → ${esc(data.word)}` : "";
      const w = esc(word).replace(/'/g, "\\'");
      const owner = word !== currentWord || named ? `<div class="d-owner">📖 ${esc(word)}${named}</div>` : "";
      box.innerHTML = owner + esc(data.detail) +
        ` <a class="regen-link" onclick="showDetail('${w}', true)">🔄重写</a>`;
      box.dataset.loaded = "1";
      box.dataset.raw = data.detail;   // 对话条把它当上下文用
    }

    async function fetchDetail(word, force) {
      const flavor = document.getElementById("flavor-input").value;
      // 把侧栏词条的注释带上,句式输入推断指向时需要上下文
      const el = document.querySelector(`.s-item[data-word="${CSS.escape(word)}"]`);
      const ctx = el
        ? `${word}(${el.querySelector(".note")?.textContent ?? ""})`
        : (currentWord ? `关于「${currentWord}」的介绍` : "");
      const resp = await fetch(`/api/expand?word=${encodeURIComponent(word)}&mode=detail&flavor=${encodeURIComponent(flavor)}${force ? "&force=1" : ""}&ctx=${encodeURIComponent(ctx)}`);
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.error || body.statusText);
      return body.data;
    }

    /* 右栏的详情框是所有词共用的:detailOwner 记着当前展示谁,换词就重新生成 */
    async function showDetail(word, force) {
      const box = document.getElementById("center-detail");
      box.hidden = false;
      if (!force && box.dataset.loaded === "1" && box.dataset.owner === word) return;
      closeCenterBoxes("center-detail");
      box.dataset.owner = word;
      box.textContent = force ? `「${word}」重写中…(换一次骰子)` : `查「${word}」的详情中…`;
      try {
        renderDetailInto(box, word, await fetchDetail(word, force));
      } catch (err) {
        // 详情偶发解析失败(句式输入尤其),自动降级为追问式解释,保证有答案
        try {
          const q = `解释这个说法(它出自关于「${currentWord}」的介绍):「${word}」`;
          const resp2 = await fetch(`/api/ask?word=${encodeURIComponent(currentWord)}&q=${encodeURIComponent(q)}`);
          const body2 = await resp2.json();
          if (!resp2.ok) throw new Error(body2.error || body2.statusText);
          box.textContent = `【${word}】` + body2.data.answer + "\n(降级为追问式解释)";
          box.dataset.loaded = "1";
          box.dataset.raw = body2.data.answer;
        } catch (err2) {
          box.textContent = "出错:" + (err2.message || err.message);
        }
      }
    }
    /* 中心词的📖详情:开着且是同一个词 → 收起;否则加载 */
    function toggleDetail(word) {
      const box = document.getElementById("center-detail");
      if (!box.hidden && box.dataset.owner === word) { box.hidden = true; return; }
      showDetail(word, false);
    }

    