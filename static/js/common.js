function esc(s) {
      return String(s ?? "").replace(/[&<>"']/g,
        c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }
    function links(w) {
      const e = encodeURIComponent(w);
      return `<span class="links">
    <a href="https://search.bilibili.com/all?keyword=${e}" target="_blank">B站</a>
    <a href="https://baike.baidu.com/search?word=${e}" target="_blank">百科</a>
    <a href="https://weixin.sogou.com/weixin?type=2&query=${e}" target="_blank">公众号</a>
  </span>`;
    }
    /* 手风琴:中心区一次只开一个内容盒。各开盒路径(showDetail/toggleThinking/roamData/openChat/openNote)进来先调它 */
    const CENTER_BOXES = ["center-detail", "center-think", "center-roamdata", "center-chat", "center-note"];
    function closeCenterBoxes(except) {
      for (const id of CENTER_BOXES) {
        if (id !== except) {
          const el = document.getElementById(id);
          if (el) el.hidden = true;
        }
      }
    }

    