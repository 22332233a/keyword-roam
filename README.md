# 关键词漫游器

给一个词,机器吐出它的**上级分类、下级分类、相邻词**(各配一句"为什么值得搜"的说明),
你挑有意思的点了去 B 站搜视频看——半娱乐半学习的关键词兔子洞。

## 启动

**方式一(切供应商推荐)**:双击 `启动-自选供应商.bat`,按提示依次粘贴
BASE_URL、API Key、模型名(它会自动帮你查该端点有哪些模型),回车即启动。

**方式二(默认 DeepSeek)**:直接

```powershell
python app.py
# 浏览器打开 http://127.0.0.1:8765
```

**方式三(装成桌面应用)**:用上面任一种启动后,浏览器地址栏右侧会出现「安装」图标
(或菜单 →「应用」→「安装此站点为应用」),装完就是**独立窗口 + 桌面图标**,
界面外壳离线也能打开(`/api/*` 仍走本地服务)。这是 PWA,只在
`localhost`/`127.0.0.1`/https 下生效。

**端点/key/模型填哪里**:启动后进 **⚙设置 →「模型接口」**填,或者设环境变量
(见文末)。设置优先于环境变量,且**留空的字段各自回落环境变量**——所以可以只改模型名。
改完即生效,不用重启。

## 怎么玩

1. 顶部输入任意词(比如 `OpenClaw`、`明朝海禁`、`咖啡豆`),回车;
2. 主区自动展开 **🧭漫游结果**:三组词卡(点任何**词**以它为中心继续漫游,点 **B站/百科/公众号** 跳搜索);
   主区是手风琴——详情/漫游结果/思考过程一次开一个;
3. 觉得某个词值得认真挖,点 **🔍深挖**:AI 先判断词的类型(事件/人物/概念/地点/组织…),
   再按类型生成 4~6 个专属维度——事件给时间线/关键人物/后果,概念给起源/误解/争议,依此类推;
4. **📖详情**给出 150 字解释;在详情文字里**划选任何不熟悉的词**,会浮出"是什么?/追问…"菜单——
   "是什么"查该词的解释,"追问"会展开底部的 **💬对话条**:绑在当前词上的多轮追问,每轮带详情原文
   和最近 6 轮上下文,300 字封顶;对话会话级保存(刷新即清),首轮问答进缓存,同问题再问不花钱;
5. 绿色词 = 漫游过(读缓存,不花钱);底部"足迹"是走过整条路,重启不丢;
6. 顶部 **🗺地图**把足迹画成活的词图:节点越大关系越多(绿=漫游 紫=深挖 蓝=详情),
   拖词整理布局、拖背景平移、滚轮缩放,点词直接跳转;
   点 **🔗两词路径**再先后点两个词,BFS 高亮出最短关联链(勾选"显示没走过的邻居"可穿过前沿词);
7. 顶部 **⚙设置**:**模型接口**(端点/Key/模型/max_tokens——留空则回落环境变量,
   带「测试连接」:会拉一次模型列表,并把连不上/路径错/Key失效/模型名不在列表里分开报;
   改完即生效不用重启)、口味预设一键填入漫游框(也可存自己的)、详情长度三档(80/150/300字)、
   放飞程度(稳/标准/抽风,即生成温度)、**黑名单**(永不推荐的词,词卡 🚫 一键拉黑,可解禁)、
   **足迹导出**(JSON 完整备份 / Markdown 可读词表——删缓存=地图清零,记得常备份)。
   存在 `data/settings.json`,即点即存,下一次生成起生效,已缓存的旧数据不动。
   API Key 存进 `settings.json`,且**后端从不把它回传给前端**(设置面板只显示头尾各4位的掩码;
   导出备份也不含 key)——所以别把 `data/settings.json` 提交到公开仓库;
8. 词卡上的 **🎲重掷**:清掉这个词当前页模式(漫游/深挖)的缓存花钱重新生成——
   详情卡另有 🔄重写。LSTM 式的"合法但偷懒"轮到自己动手治;
9. **🧭漫游结果**顶部的 **📚整树补详情**是"学习模式":一键给这棵树里所有缺详情的词
   批量生成 📖 详情(逐条调现有接口,进度可看、可随时停,已有详情和黑名单词自动跳过,
   明码标价确认后才开跑)——想把某个词连根读完,点它;
10. **📝笔记**是左侧常驻栏,绑在当前词上:看了什么视频、自己的理解、下回想挖的小径,停手
    半秒自动存(`data/notes.json`,重启不丢),清空即删除;换词自动跟随,📝按钮可把左栏收成细条;
    笔记会随足迹一起导出;
11. "口味偏好"栏可以改,比如"越离谱越好"或"只看历史向"——AI 会照办;
12. **自动补详情**(⚙设置里可调,默认开):漫游结果一出来,后台就顺手把 **⬇下级 + ↔相邻**
    这两组词的 📖 详情排队生成——你接着点任意一个,右栏直接有内容,不用等、不用手点。
    三条规矩:串行跑(并发 1,不跟你正在看的词抢)、间隔 800ms(不撞限流)、**只在后台写缓存**
    (绝不改右栏内容,否则你想看 A 却跳出 B)。换词后旧队列继续跑完(钱已经花了)。
    进度显示在漫游结果盒的工具栏(`自动补详情 3/12…`)。三档:**关** / **智能(仅下级+相邻)** / **全部(含上级)**。
    代价:一轮约 8~14 条,一毛钱上下。嫌打扰就设成「关」——功能整体停用,已生成的详情不受影响。
13. **反复生成不出来的词会被自动跳过**:有些词模型总写不完整(句子说到一半),校验不过就进不了缓存,
    以前每漫游一次、每次刷新后重进都会再为它花一次钱,永远好不了。现在连续失败 3 次就记账跳过,
    自动补详情不再碰它(进度条会显示`失败 N,点这里重试`)。修好 API key / 换了模型,
    点一下那句进度文字就能把卡住的词强制重跑;手动点 📖 或 🔄重写也照样能试。

## 成本

单次查询约 0.5~1 分钱(输入 ~1k token、输出 ~800 token)。查过的词全部缓存,
不再请求,所以玩得越久、新词越少、账单增速越慢。缓存存在 `data/cache.json`,
删掉它 = 地图清零(慎删,那是你的足迹)。

## 缓存预热(可选)

想把词图一次铺大,不用一个个点,`batch.py` 给了三条路,挑词/提示词/校验/合并完全同源:

**会话模型直生成(零 API 费,适合补几个词/烟测)**:出题文件交给对话里的 AI 答卷,收卷照常校验入库:

```bash
python batch.py agent-prepare --mode basic --scope neighbors --limit 5
# 让对话里的模型按 data/agent_in/todo-*.jsonl 里每条的 system+user 生成正文,
# 写成答卷 jsonl(每行 {"custom_id":"basic-0","content":"<生成的原文>"})
python batch.py agent-merge todo-xxx.jsonl 答卷.jsonl
```

**在线并发(推荐,快,全价)**:平台限流 RPM=100/TPM=10M,几十条也就一两分钟,不用排队:

```bash
python batch.py prewarm --mode detail --scope missing                # 缺详情的全补上
python batch.py prewarm --mode basic --mode deep --word Transformer  # 漫游+深挖混着跑
python batch.py prewarm --mode detail --scope related --word 大语言模型 --word kimi
# related = 这几棵树(漫游+深挖)里出现过的每个词都补详情,已有详情的自动跳过
```

`--concurrency` 默认 8(超限会 429,已带退避);失败重跑同一句即可,按 scope 挑词只挑还缺的。

**离线批量(便宜,要排队,适合几百上千条过夜跑)**:批量推理是异步通道,半价但结果要等:

```bash
setx ROAM_BATCH_BASE_URL "https://batch-api-<region>.xiaomimimo.com"  # 从批量推理页面抄
python batch.py submit --mode detail --scope missing   # 挑词→生成 JSONL→上传→建任务
python batch.py poll                                   # 查进度(加 --watch 300 循环盯)
python batch.py ingest <batch_id>                      # 下结果→校验→并进 cache.json
```

- `--scope missing` 挑缓存里缺该模式的词;`--scope neighbors` 挑漫游图里还没走过的词;
  也可 `--word 词 --word 词` 指定;`--dry-run` 只生成 `data/batch_in/*.jsonl` 不上传。
- **主题式铺图**(漫游→深挖→详情):详情依赖前两轮产出的词表,在线用 prewarm 串着跑就行,
  离线批量则要三轮、两批之间先 `ingest`;互不依赖的批次要并行提交——批量是低优先级共享算力,
  排队是常态,任务越少等得越少(`--mode` 可重复,把漫游和深挖混进一个文件就省一个队列位)。
- 生成的 JSONL 与官方模板 `data/demo.jsonl` 同构,提示词与在线请求共用同一套拼装
  (`app.py` 的 `build_prompt`),回填合并也共用 `merge_into_cache`——两条路不会走样。
- 校验不过(详情腰斩等)的词进任务的重掷队列:`python batch.py submit --retry <batch_id>`
  再掷一轮,对应在线的"校验不过自动重掷一次"。
- 任务记录在 `data/batch_jobs.json`,结果文件在 `data/batch_out/`;
  接口失败和异常同步记进 `data/abnormal.log`。
- 平台限制:单文件 ≤ 128MB、单批 ≤ 50,000 请求、最长等待 1~14 天(创建后不可改)。
  最长等待用 `--days 7`(对齐控制台那个"天"输入框,默认 7 天)或 `--window 24h` 原样透传;
  文档只给过 `"24h"` 示例,若平台不认 `168h` 就改回 `--window 24h`。
- 不想配 Base URL 也行——`--dry-run` 生成的 jsonl 可以直接拖进平台「创建批量任务」页面,
  跑完下载结果文件再用 `ingest-file` 回填(靠同名 `.map.json` 把 custom_id 对回词):

  ```bash
  python batch.py ingest-file data/batch_in/xxx.jsonl 下载的output.jsonl [--errors 下载的errors.jsonl]
  ```

  不过关的词会自动拼成 `xxx.retry.jsonl`,再传一次即可。
- 提醒:任务完成后尽快 `ingest`,平台只留数据 30 天。先拿两个词烟测更稳
  (`python batch.py submit --mode detail --word 咖啡豆 --word 猫 --dry-run` 只出文件,
  确认无误去掉 `--dry-run` 真提交)。

## 测试

零依赖:Python 用标准库 `unittest`,前端用 Node 内置 `vm`。**不需要装任何东西**。

```bash
python -m unittest discover -s tests -t .   # 后端 116 条
node tests/js/run_frontend_tests.mjs        # 前端  30 条
```

**三条规矩**(写在 `tests/support.py` 顶部,踩过坑才立的):

1. **绝不打真实 API**。全部用本地假端点,并且全局拦截 `socket.connect`——只放行 `127.0.0.1`。
   万一哪天配置写错,测试会**报错**而不是花你的钱。吃过这个亏:有一版测试撞上 ⚙设置 里的真 key,
   偷偷打了几条真请求(优先级是 设置 > 环境变量,测试设的端点被无视了)。
2. **绝不碰真实数据**。所有读写指向一次性临时目录,跑完自动删。
3. 前端测试用 `vm` 把 `static/js/autodetail.js` **原样**跑起来(配一套假 DOM),
   测的是真代码,不是复制品。

测哪些东西:

| 文件 | 覆盖 |
|---|---|
| `tests/test_store.py` | 合并语义(不许冲掉已生成的 deep/detail)、失败记账、设置规范化、key 永不出后端 |
| `tests/test_llm.py` | 校验闸门(腰斩/超长/过稀)、JSON 容错解析、断引语抢救、提示词拼装、配置优先级 |
| `tests/test_api.py` | 全部 `/api/*` 路由的正常与异常路径、错误分类、导出不含 key |
| `tests/test_detail_failguard.py` | 「生成不出的词不再反复烧钱」端到端(走真实 HTTP 端点) |
| `tests/js/run_frontend_tests.mjs` | 自动补详情的入队判据、失败退避、进度口径、并发闸门 |

## 架构

每个文件是谁、一次漫游的十二站旅程、改代码不能破的不变量——见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 文件

| 文件 | 干什么 |
|---|---|
| `app.py` | Flask 后端:全部路由(漫游/追问/对话/笔记/地图/导出/设置)+ 启动 |
| `store.py` | 数据层:四份 JSON(cache/asks/notes/settings)与 abnormal.log 的读写、合并语义 |
| `llm.py` | LLM 层:五套提示词、`chat()` 请求、JSON 解析、校验重掷、`build_prompt` 流水线 |
| `templates/index.html` | 前端页面骨架(原生 JS,无框架) |
| `static/js/` | 前端脚本(按功能拆分:state/common/roam/roamdata/detail/chat/note/map/footprint/selection/main/sidebar/settings) |
| `static/css/style.css` | 全部样式 |
| `static/sw.js` + `static/manifest.json` | PWA:让页面能被装成桌面应用、外壳离线可用(`/sw.js` 由后端从根路径提供,否则作用域被限死) |
| `static/icons/` | PWA 图标(192/512/512-maskable) |
| `batch.py` | 缓存预热旁路工具:在线并发 `prewarm`(快)或离线批量 `submit/poll/ingest`(省)、会话模型直生成 `agent-prepare/agent-merge` |
| `tests/` | 测试(标准库 unittest + Node vm,零依赖);`tests/support.py` 是隔离脚手架 |
| `data/cache.json` | 关键词图缓存(运行后生成) |
| `data/settings.json` | 用户设置(**含 API Key**,别提交到公开仓库) |

## 可调参数(环境变量)

**优先级**:⚙设置里的「模型接口」> 环境变量 > 下面的默认值。设置里留空的字段各自回落环境变量。

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_BASE_URL` | `https://api.deepseek.com` | **万能插座**:任何 OpenAI 兼容端点都能接(Ollama 填 `http://localhost:11434/v1`) |
| `LLM_API_KEY` | 无 | 对应端点的 key;未设时回退读 `DEEPSEEK_API_KEY`(本地端点可不填) |
| `LLM_MODEL` | 未设时回退 `DEEPSEEK_MODEL` → `deepseek-flash` | 模型名必须与该端点的模型列表逐字一致 |
| `ROAM_BATCH_BASE_URL` | 无 | 批量推理 Base URL(仅 `batch.py` 用);从批量推理页面抄 |
| `ROAM_PORT` | `8765` | 端口被占时换一个 |
| `ROAM_MAX_TOKENS` | `8000` | 思维链+正文共用预算;大词(如微软)思考就要两千 token,报"解析失败"可再调大 |

环境变量是**启动时读一次**(`llm.py` 顶部);⚙设置则是**每次请求现读**,所以改设置不用重启。
两者都改过时,设置优先——这也是为什么老用法(`setx`)不用动就能继续用。

**本地模型提示**:Ollama/LM Studio 等都讲 OpenAI 兼容协议,填 `LLM_BASE_URL` 即接。但 JSON 输出
的可靠性随模型规模下降,建议 30B 级别以上;小模型偶发返回断 JSON,后端的兜底解析器能救一部分。

**Ollama 跨域**:浏览器直连本地 Ollama 会被 CORS 挡(默认只允许同源),需要设
`OLLAMA_ORIGINS=*`(或把你访问的地址加进去)再启动 Ollama。服务端没有这个限制,
所以 `python app.py` 这条路不受影响——受影响的是纯浏览器版/前端直连的部署形态。

## 已知边界

- 提示词里要求"至少 2 个跨界词",但"有意思浓度"依赖模型发挥,口味不对就多试几次口味栏;
- 偶尔模型返回的 JSON 不合法——已内置**自动重试一次**(温度高就是掷骰子,重掷通常就好);
  重试仍失败才报错。detail/追问场景温度降为 0.7 求稳,漫游/深挖保持 1.1 求惊喜;
- 缓存是单文件 JSON,单人用没问题;想多人/多设备用再升级 SQLite;
- **Windows 坑:改了代码重启后"还是老样子"?** Ctrl+C 偶尔杀不干净旧进程——Windows 允许新旧两个进程
  同时"成功"绑定 8765,但连接仍被老进程接走,于是你重启了个寂寞。自查:
  `netstat -ano | findstr :8765` 看有几个 LISTENING,多个就 `taskkill /PID 进程号 /F` 全毙掉再启动;
- 模板/后端改动都要重启后端才生效(Flask 非 debug 模式缓存模板);只有 data/cache.json 是即时读的。
