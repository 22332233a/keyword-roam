// 启动时从后端加载历史足迹(存在 data/cache.json 里,重启不丢)
    async function loadHistory() {
      try {
        const resp = await fetch("/api/cache");
        const body = await resp.json();
        for (const it of body.words) {
          visited.set(it.word, { feats: it.feats ?? [], time: it.time ?? 0 });
          // 反复生成不出详情的词:启动就把退避铺好,自动补详情不会再为它们白发一次请求
          if (it.failed) autoFail.set(it.word, it.failed);
        }
        renderChips();
      } catch (err) { /* 加载失败就当没有历史,不影响使用 */ }
    }
    loadHistory();

    document.getElementById("word-input").addEventListener("keydown", e => {
      if (e.key === "Enter") roamFromInput();
    });
  