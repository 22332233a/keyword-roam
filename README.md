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
7. 顶部 **⚙设置**:口味预设一键填入漫游框(也可存自己的)、详情长度三档(80/150/300字)、
   放飞程度(稳/标准/抽风,即生成温度)、**黑名单**(永不推荐的词,词卡 🚫 一键拉黑,可解禁)、
   **足迹导出**(JSON 完整备份 / Markdown 可读词表——删缓存=地图清零,记得常备份)。
   存在 `data/settings.json`,即点即存,下一次生成起生效,已缓存的旧数据不动;
8. 词卡上的 **🎲重掷**:清掉这个词当前页模式(漫游/深挖)的缓存花钱重新生成——
   详情卡另有 🔄重写。LSTM 式的"合法但偷懒"轮到自己动手治;
9. **🧭漫游结果**顶部的 **📚整树补详情**是"学习模式":一键给这棵树里所有缺详情的词
   批量生成 📖 详情(逐条调现有接口,进度可看、可随时停,已有详情和黑名单词自动跳过,
   明码标价确认后才开跑)——想把某个词连根读完,点它;
10. **📝笔记**是左侧常驻栏,绑在当前词上:看了什么视频、自己的理解、下回想挖的小径,停手
    半秒自动存(`data/notes.json`,重启不丢),清空即删除;换词自动跟随,📝按钮可把左栏收成细条;
    笔记会随足迹一起导出;
11. "口味偏好"栏可以改,比如"越离谱越好"或"只看历史向"——AI 会照办。

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

## 文件

| 文件 | 干什么 |
|---|---|
| `app.py` | Flask 后端:两个 API(`/api/expand` 漫游、`/api/cache` 足迹统计)+ 缓存 |
| `templates/index.html` | 前端页面(原生 JS,无框架) |
| `batch.py` | 缓存预热旁路工具:在线并发 `prewarm`(快)或离线批量 `submit/poll/ingest`(省) |
| `data/cache.json` | 关键词图缓存(运行后生成) |

## 可调参数(环境变量)

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_BASE_URL` | `https://api.deepseek.com` | **万能插座**:任何 OpenAI 兼容端点都能接(Ollama 填 `http://localhost:11434/v1`) |
| `LLM_API_KEY` | 无 | 对应端点的 key;未设时回退读 `DEEPSEEK_API_KEY`(本地端点可不填) |
| `LLM_MODEL` | 未设时回退 `DEEPSEEK_MODEL` → `deepseek-flash` | 模型名必须与该端点的模型列表逐字一致 |
| `ROAM_BATCH_BASE_URL` | 无 | 批量推理 Base URL(仅 `batch.py` 用);从批量推理页面抄 |
| `ROAM_PORT` | `8765` | 端口被占时换一个 |
| `ROAM_MAX_TOKENS` | `8000` | 思维链+正文共用预算;大词(如微软)思考就要两千 token,报"解析失败"可再调大 |

**本地模型提示**:Ollama/LM Studio 等都讲 OpenAI 兼容协议,填 `LLM_BASE_URL` 即接。但 JSON 输出
的可靠性随模型规模下降,建议 30B 级别以上;小模型偶发返回断 JSON,后端的兜底解析器能救一部分。

## 已知边界

- 提示词里要求"至少 2 个跨界词",但"有意思浓度"依赖模型发挥,口味不对就多试几次口味栏;
- 偶尔模型返回的 JSON 不合法——已内置**自动重试一次**(温度高就是掷骰子,重掷通常就好);
  重试仍失败才报错。detail/追问场景温度降为 0.7 求稳,漫游/深挖保持 1.1 求惊喜;
- 缓存是单文件 JSON,单人用没问题;想多人/多设备用再升级 SQLite;
- **Windows 坑:改了代码重启后"还是老样子"?** Ctrl+C 偶尔杀不干净旧进程——Windows 允许新旧两个进程
  同时"成功"绑定 8765,但连接仍被老进程接走,于是你重启了个寂寞。自查:
  `netstat -ano | findstr :8765` 看有几个 LISTENING,多个就 `taskkill /PID 进程号 /F` 全毙掉再启动;
- 模板/后端改动都要重启后端才生效(Flask 非 debug 模式缓存模板);只有 data/cache.json 是即时读的。
