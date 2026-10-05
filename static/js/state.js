
    const visited = new Map();   // word -> {feats:[roam/deep/detail], time}
    let currentWord = "";   // 当前中心词,追问时作为上下文
    let currentViewMode = "basic";   // 当前页面模式:仅 🎲重掷在用(点词已固定=漫游)

    