---
name: keyword-roam-session-gen
description: 用当前会话的模型（零 API 费）批量生成 keyword-roam 的漫游/深挖/详情数据并并入 data/cache.json。当用户要"在当前会话里生成/铺数据""你自己把漫游/深挖/详情补一批""不花钱生成""把某个词（漫游树或深挖树）里的词补详情"时使用。走 batch.py 的 agent-prepare → 我答卷 → agent-merge 通道，全程不打 API；要打 API 的预热/离线批量/排障请改用 keyword-roam-prewarm。
---

# 会话内批量生成 keyword-roam 数据（零 API 费）

**我就是生成器**：`batch.py` 出题 → 我按题生成正文 → `batch.py` 收卷、校验、并入 `data/cache.json`。
提示词/校验/合并都与在线请求同源（`build_prompt` / `_validate` / `merge_into_cache`），
所以这条路和花钱的 prewarm 产出一致，只是把答卷人从模型 API 换成了当前会话的我。

与 `keyword-roam-prewarm` 的分工：那边是打 API 的 prewarm / 离线批量 / 排障；
**本技能不打任何 API，成本是我的上下文**。

## 三类目标 → 三组出题命令

| 用户想要 | `--mode` | 作用域 |
|---|---|---|
| 漫游：给词出 上级/下级/相邻 | `basic` | `--scope missing`（缓存里缺漫游的词）或 `--scope neighbors`（漫游图里提到但没走过的词＝往外铺） |
| 深挖：按词的类型出维度 | `deep` | `--scope missing` |
| 某棵树里的词补详情 | `detail` | `--scope related --word <根词>`（把这棵漫游树＋深挖树里出现过的词都收进来，已有详情的自动跳过） |

```bash
python batch.py agent-prepare --mode basic  --scope neighbors --limit 8
python batch.py agent-prepare --mode deep   --scope missing   --limit 8
python batch.py agent-prepare --mode detail --scope related --word 大语言模型 --limit 20
```

- 出题前先估规模，`--limit` 控制这一轮出多少题。
- `--word` 是**跨模式全局**的（argparse 只有一个 `--word` 列表）：要给不同模式指定不同词，就分开跑几次。
- 详情依赖树已存在：先 basic/deep 把那棵树生成出来，再 `--scope related` 补详情。
- 出题文件名带时间戳，同一秒重复出题会自动加后缀，别把两份题当同一份。

## 动手前（必做）

1. **Flask 服务别在跑**：`save_cache` 是整文件覆写、无跨进程锁，服务端和这里同时写 `cache.json`
   会互相覆盖丢数据。确认端口没挂 app.py；在跑就请用户停掉，不要自己杀。
2. `git status` 看一眼：`data/cache.json` 等数据文件**不提交**（用户政策），别顺手 add 进去。
3. 记下当前缓存词数，收尾对账：
   `python -c "import json;print(len(json.load(open('data/cache.json',encoding='utf-8'))))"`

## 流程

### 1. 出题
跑上面的 `agent-prepare`，它写出 `data/agent_in/todo-<时间戳>-<模式>.jsonl`，每行含该词的真实提示词：
`{..., "system": "...", "user": "..."}`。**`system`＋`user` 就是该词的完整提示词**（已含口味偏好、
已访问词表、黑名单、上下文片段）——照它生成，别自己发明格式。

看 todo 里的中文：在 Bash 里跑 python 打印要加 `PYTHONIOENCODING=utf-8`（Windows 控制台默认按 GBK
输出会乱码），或者直接用 Read 工具读文件。

### 2. 答卷（我逐条生成）
读那份 todo，逐条按 `system`＋`user` 生成正文，写成本地答卷 jsonl，每行：

```
{"custom_id": "<todo 里那条的 custom_id>", "content": "<生成的 JSON 正文>"}
```

**content 必须是合法 JSON 正文文本**（`parse_llm_json` 容忍 ```json 围栏和前后废话，但语法要对）。

**写答卷文件别手写 JSONL 转义**——几十条里错一个引号就整行报废。用 python heredoc 让 `json.dumps`
负责转义，正文放三引号里、内部双引号原样写：

```bash
PYTHONIOENCODING=utf-8 python - > data/agent_in/answers-<时间戳>.jsonl <<'PY'
import json
items = [
  ("detail-0", """{"word":"火人节","detail":"每年在内华达黑石沙漠举办的狂欢……最后一把火烧掉。"}"""),
  ("detail-1", """{"word":"...","detail":"...。"}"""),
]
for cid, content in items:
    print(json.dumps({"custom_id": cid, "content": content}, ensure_ascii=False))
PY
```

- `<<'PY'` 引号定界防变量展开；`PYTHONIOENCODING=utf-8` 必须加，否则 Windows 下按 GBK 落盘、
  `agent-merge` 读成乱码。
- 正文**文本内**的引号仍一律用「」，不用 ASCII 双引号。
- **每轮 5~8 条**为宜（详情词短，可放宽到 ~13 条）；再多注意力被摊薄。量大就分批循环（见第 4 步）。
- 收卷前先自校验（`json.loads` 可解析 ＋ 字数达标 ＋ 句读收尾），比等 `agent-merge` 报错快。

各模式正文形状与**校验硬下限**（不过关会被点名重来）：

| 模式 | 正文 JSON 形状 | 硬下限（`_validate`） |
|---|---|---|
| basic | `{"word":"中心词","parents":[{"word","note"}],"children":[...],"similar":[...]}` | parents≥1、children≥3、similar≥5；similar 里至少 2 个跳出本领域的词 |
| deep | `{"type":"类型","summary":"一句定位","dimensions":[{"name","items":[{"word","note"}]}]}` | 维度≥3 且条目总数≥8 |
| detail | `{"word":"...","detail":"解释"}` | 按 ⚙详情长度档位 ≤160/300/460 字（默认标准=300），且**以句读收尾**（。！？…」等）——半句话判腰斩 |

- 附加质量要求（来自提示词，校验不查但照做）：所有 `note` ≤15 字；词真实存在、不生造、不拼接。

答卷文件原始一行（`content` 里装着一段 JSON 文本——用上面 heredoc 写法时，这层转义由 `json.dumps` 自动生成，不用手写）：

```
{"custom_id":"basic-0","content":"{\"word\":\"咖啡豆\",\"parents\":[{\"word\":\"农产品\",\"note\":\"期货市场的重头戏\"}],\"children\":[...],\"similar\":[...]}"}
```

### 3. 收卷
```bash
python batch.py agent-merge todo-xxx.jsonl 答卷.jsonl
```
答卷文件名不给路径会自动到 `data/agent_in/` 下找。它会逐条 parse→校验→并入缓存，来源标成 `src:"agent"`，
不过关的**点名打印**（`词(模式):原因`）。

### 4. 失败重收 / 大批量循环
- 点名的那几条：只重写它们的 content（其余不动）再 `agent-merge` 一次——合并按 词＋模式 覆盖，重复收不会重复计。
- 要生成很多词：反复 `agent-prepare`（`missing`/`related` 会自然跳过已完成的）→ 生成 → merge，
  直到提示"没有可生成的目标"。

## 收尾
- 前后各报一次缓存词数（差值＝新增），并扫 `data/abnormal.log` 尾部的新行，汇报"成功 N / 异常 M 及原因"。
- `git status` 确认只有数据文件变更（正常，不提交）。

## 红线
- 不打 API；不绕过 `build_prompt` / `_validate` / `merge_into_cache`——这三处是两条路同源的核心约定。
- 校验不过别调低阈值，尤其详情"腰斩"：那说明真的只说了一半，重写，不是放宽。
