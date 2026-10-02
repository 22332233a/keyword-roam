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
    /* 手风琴:主区一次只开一个 AI 显示盒(详情/思考/漫游结果)。
       对话=底部条、笔记=左栏,两者是常驻工作区,不参与互斥 */
    const CENTER_BOXES = ["center-detail", "center-think", "center-roamdata"];
    function closeCenterBoxes(except) {
      for (const id of CENTER_BOXES) {
        if (id !== except) {
          const el = document.getElementById(id);
          if (el) el.hidden = true;
        }
      }
    }

    