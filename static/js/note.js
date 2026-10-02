/* ===== 📝笔记:绑在当前词上的手写便签,一词一条,停手自动存,重启不丢(data/notes.json) ===== */
let noteSaveTimer = null;

function toggleNote() {
  const box = document.getElementById("center-note");
  if (!box) return;
  if (!box.hidden) { box.hidden = true; return; }
  openNote();
}

async function openNote() {
  const box = document.getElementById("center-note");
  if (!box) return;
  closeCenterBoxes("center-note");
  box.hidden = false;
  box.innerHTML = `<b>📝 笔记「${esc(currentWord)}」</b>
  <textarea id="note-input" placeholder="写点什么:看了哪些视频、自己的理解、下回想挖的小径…"></textarea>
  <span class="note-status" id="note-status"></span>`;
  const ta = document.getElementById("note-input");
  try {
    const resp = await fetch(`/api/note?word=${encodeURIComponent(currentWord)}`);
    ta.value = (await resp.json()).text ?? "";
  } catch { /* 拉不到就当空白笔记 */ }
  ta.addEventListener("input", () => {
    clearTimeout(noteSaveTimer);
    const st = document.getElementById("note-status");
    if (st) st.textContent = "…";
    noteSaveTimer = setTimeout(saveNote, 600);   // 停手半秒自动存,不打断写字
  });
  ta.focus();
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
