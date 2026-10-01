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

    