/* ===== 旧左栏已退役(2026-10-02 布局重写):漫游/深挖的分组卡片移进主区 🧭漫游结果盒 =====
       本文件只剩足迹"去过"变色的小工具,漫游/深挖完成后由调用方刷新 seen 状态 */
    function refreshSeen(root) {
      (root ?? document).querySelectorAll(".s-item").forEach(el => {
        el.classList.toggle("seen", visited.has(el.dataset.word));
      });
    }
