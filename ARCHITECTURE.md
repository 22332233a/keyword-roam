# 架构导读(ARCHITECTURE.md)

> 这份文档回答三个问题:**每个文件是谁**、**一次点击经过了哪些站**、**哪些约定改代码时不能破**。
> 不讲代码细节——细节在源码里,这里给你的是地图和阅读顺序。
> 维护约定:改了模块职责/请求流水线/不变量,顺手更新本文件。

## 一、地图:每个文件是谁

### Python(后端三层)

| 文件 | 是谁 | 什么时候会改到它 |
|---|---|---|
| `app.py` | **路由层**:11 个 API + 启动,一行业务逻辑没有 | 加新接口、改参数校验 |
| `store.py` | **数据层**:cache/asks/notes/settings 四份 JSON + abnormal.log 的读写、用户设置、合并语义 | 加新数据文件、改数据格式 |
| `llm.py` | **LLM 层**:五套提示词、`chat()` 请求、JSON 解析、校验、`build_prompt` 流水线 | 改提示词、改校验规则、换模型参数 |
| `batch.py` | **旁路 CLI**(独立运行):prewarm 在线预热 / submit 离线批量 / agent-prepare+merge 会话模型直生成 | 改预热策略(它 import 的是 app/llm/store,不反向依赖) |

依赖方向单向:`app → llm → store`,以及 `app → store`。谁也不反向 import。

### 前端(templates + static)

| 文件 | 是谁 |
|---|---|
| `templates/index.html` | 页面骨架:三区布局的静态结构(左词卡/笔记列、中主区、右目录、底对话条) |
| `state.js` | 全局状态:visited Map(足迹)、currentWord、currentViewMode |
| `common.js` | 小工具:esc/links/手风琴 closeCenterBoxes |
| `roam.js` | 漫游核心:go/goWord/rerollWord、renderCenter/renderBasic/renderDeep |
| `roamdata.js` | 🧭漫游结果盒:分组卡片、📚整树补详情(队列+防重入)、🚫拉黑 |
| `detail.js` | 📖详情:fetch/降级链(失败转 ask)/渲染 |
| `chat.js` | 💬对话底栏:多轮历史、regen 重新回答、上下文拼接 |
| `note.js` | 📝笔记列:防抖自动存、换词跟随 |
| `autodetail.js` | 自动补详情:漫游后后台排队给下级/相邻词补详情(串行、失败退避) |
| `map.js` | 🗺足迹地图:力导向布局、BFS 两词路径 |
| `footprint.js` | 底部足迹 chips:筛选/排序/搜索 |
| `selection.js` | 划词菜单:"是什么"/"追问" |
| `settings.js` | ⚙设置面板:口味/详情长度/放飞/黑名单/导出 |
| `sidebar.js` | 左栏词卡渲染 + 右侧目录(与笔记列接力显隐) |

### 其他

| 位置 | 是谁 |
|---|---|
| `data/*.json` | **你的数据**(cache 足迹图/asks 追问/notes 笔记/settings 偏好)——不进 git,settings.json 含 key 更不能进 |
| `data/abnormal.log` | 异常留痕:腰斩/空返回/校验不过,排查数据问题的第一现场 |
| `tests/` | 116 例测试套件(假 LLM 端点 + 网络闸门 + 数据隔离),`python -m unittest discover -s tests` |
| `.agents/skills/` | 两个技能包:prewarm(API 预热运维)、session-gen(会话模型零费直生成) |

## 二、一次漫游的完整旅程

在输入框敲下"咖啡豆"回车,到字节落进 cache.json,共十二站:

```
[前端]                                        [后端]
1. 输入框回车 → roam("咖啡豆")          roam.js
2. go(word,"basic") → fetch /api/expand  roam.js
3. 参数校验 + load_cache()                app.py → store.py
4. 缓存命中(有 parents)? ── 是 → 返回 cached:true ──┐
5. 未命中 → call_llm()                    llm.py    │
6. build_prompt:                          llm.py    │
   读 settings(详情档位/黑名单/温度)                 │
   拼 user_msg(词+口味+已访问40+黑名单)              │
   选提示词 + 定温度                                  │
7. chat(): POST MiMo,90s 超时,重试 2 次             │
   (max_tokens 截断/空正文 → 兜底+留痕)               │
8. parse_llm_json: 容忍围栏,抠出 JSON               │
9. _validate: 字段+数量下限                          │
   不过 → 抛错 → call_llm 重掷(再来一轮 6~9)          │
10. merge_into_cache:                     store.py  │
    basic 整条写入,保留已有 deep/detail               │
11. save_cache: 落盘 data/cache.json      store.py  │
12. renderBasic: 主区+左栏词卡渲染          roam.js  │
    refreshSeen 变绿 ←──────────────────────────────┘
    autodetail 队列开始后台补详情
```

**支线**(同一流水线的变体,记住差异即可):

- **深挖** = 主线换 `mode="deep"`,提示词/校验规则换 deep 版;
- **详情** = `mode="detail"`,提示词里的"150字"按设置档位替换,校验加"结尾必须是句读"(腰斩检测);反复失败 502 → 前端降级调 `/api/ask` 出快答;
- **划词追问** = `/api/ask`,150 字,按 `词:::问题` 缓存(首轮进缓存,同问题再问免费);
- **对话** = `/api/chat`(POST),350 字,带最近 6 轮历史+详情原文,`regen:true` 跳缓存重新回答。

## 三、不变量清单(改代码前必读)

1. **单一 LLM 出口**:`chat()` 是全项目唯一发 LLM 请求的函数。新功能要接模型,调它,别自己写 requests。
2. **三共用**:提示词(`build_prompt`)、校验(`_validate`)、合并(`merge_into_cache`)在线和批量共用同一份——复制一份"稍微改改"就是这个项目最贵的错误。
3. **两层重掷**:chat 内层对网络/解析重试,call_llm 外层对校验失败重掷。最坏 4 次调用一个词。
4. **四出口校验**:basic/deep 在 `_validate`;`/api/chat` 350字+句读;`/api/ask` 200字+句读。加校验时四个出口都要检查——同一个病根(思维链吃光预算掐断正文)会在每个出口各犯一遍。
5. **合并保已有**:merge_into_cache 写 basic 时保留词条里已有的 deep/detail。回填/重掷都不许清掉它们。
6. **黑名单单独成行、永不截断**;"已访问过"列表只留最近 40 个。
7. **asks 缓存只在无上下文首轮命中**;`regen:true` 跳过它,并把新答案覆盖回同一条。
8. **降级链方向**:detail 失败 → ask 兜底,所以 ask 的校验强度永远不能低于 detail。
9. **测试纪律**:改完跑 `python -m unittest discover -s tests`;测试物理上不能出网(support.py 的 socket 闸门),别试图在测试里调真 API。
10. **数据不进 git**;settings.json 含 API key,尤其不能进。
11. **前端点词固定=漫游**,深挖只属于 🔍 按钮;足迹 chips 例外(按已有数据跳)。

## 四、读源码的建议顺序

每个 30 分钟以内,按依赖顺序:

1. `store.py` —— 最短,读完就知道"数据长什么样、怎么进出";
2. `llm.py` 的 `build_prompt` + `_validate` —— 项目的灵魂:AI 被要求什么、什么会被打回;
3. `app.py` 挑一个路由精读(推荐 `/api/expand`,它是主线的后端全貌);
4. `roam.js` 的 `go()` —— 主线的前端半程;
5. 其余按需:用到哪个读哪个。

读的时候开着测试:`tests/test_llm.py` 里的用例就是每个函数的"行为说明书",比注释还准。
