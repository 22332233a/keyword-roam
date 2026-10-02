/* ===== 📝笔记:常驻左栏,一词一条,停手自动存(data/notes.json),重启不丢 ===== */
let noteSaveTimer = null;

function toggleNote() {
  /* 📝收起/展开笔记列;目录(右侧文字速查)只在笔记收起时顶上,两者互占右缘空间 */
  const col = document.getElementById("note-col");
  if (!col) return;
  const collapsed = col.classList.toggle("collapsed");
  const toc = document.getElementById("toc");
  if (toc) toc.hidden = !collapsed;
}

/* 换词时由 renderCenter 调用:标题跟随,重新拉取该词的笔记 */
async function refreshNoteDock() {
  const title = document.getElementById("note-title");
  const ta = document.getElementById("note-input");
  if (!title || !ta) return;
  title.textContent = `📝 笔记「${currentWord}」`;
  ta.value = "";
  const st = document.getElementById("note-status");
  if (st) st.textContent = "";
  try {
    const resp = await fetch(`/api/note?word=${encodeURIComponent(currentWord)}`);
    ta.value = (await resp.json()).text ?? "";
  } catch { /* 拉不到就当空白笔记 */ }
}

async function saveNote() {
  const ta = document.getElementById("note-input");
  if (!ta) return;
  const st = document.getElementById("note-status");
  try {
    const resp = await fetch("/api/note", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word: currentWord, text: ta.value }),
    });
    if (!resp.ok) throw new Error((await resp.json()).error || resp.statusText);
    if (st) st.textContent = `已保存 ✓ ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    if (st) st.textContent = "保存失败:" + (err.message || err);
  }
}

/* 输入框是静态 DOM,脚本加载时直接挂防抖自动保存 */
document.getElementById("note-input").addEventListener("input", () => {
  clearTimeout(noteSaveTimer);
  const st = document.getElementById("note-status");
  if (st) st.textContent = "…";
  noteSaveTimer = setTimeout(saveNote, 600);   // 停手半秒自动存,不打断写字
});
