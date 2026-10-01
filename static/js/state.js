
    const visited = new Map();   // word -> {feats:[roam/deep/detail], time}
    let currentWord = "";   // 当前中心词,追问时作为上下文
    let currentViewMode = "basic";   // 当前页面模式:点关键词时继承它(漫游页点=漫游,深挖页点=深挖)

    