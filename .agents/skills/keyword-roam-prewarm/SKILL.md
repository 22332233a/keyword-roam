---
name: keyword-roam-prewarm
description: 关键词漫游器(keyword-roam)的缓存预热、批量回填与数据排障。当用户要求"预热缓存/铺图/补详情/把漫游图往外扩/回填批量结果/查批量任务"，或要排查 data/cache.json、data/abnormal.log 里的数据问题时使用——即使没说"预热"两个字。
---

# keyword-roam 预热与回填运维

单文件 Flask 工具（`app.py`），旁路工具是 `batch.py`。缓存 `data/cache.json`（键=词，
值含 parents/children/similar/deep/detail），足迹图就是这份数据的投影。当前缓存规模先看：
`python -c "import json;print(len(json.load(open('data/cache.json',encoding='utf-8'))))"`

## 前置检查（动手前必做）

1. **Flask 服务别在跑**。`save_cache` 是整文件覆写、无跨进程锁，服务端和预热端同时
   写 `cache.json` 会互相覆盖丢数据。先确认 5000 端口（或用户自定义端口）没挂着 app.py；
   在跑就请用户停掉，不要自己杀。
2. **先 dry-run 再花钱**：任何批量生成，先加 `--dry-run` 看挑中了哪些词、数量对不对，
   确认后去掉重跑。
3. 跑之前瞄一眼 `git status`：`cache.json`/`asks.json` 是不提交的（用户明确政策），
   别顺手 add 进去。

## 首选：在线并发预热（prewarm）——大批量（十几条以上）走这里

走在线端点，全价但快，RPM=100 是唯一约束（TPM≈10M 用不满）。默认并发 8，遇 429
已自带指数退避，**不要为了"更快"把并发拉到 30+**——退避风暴只会更慢。

```bash
python batch.py prewarm --mode detail --scope missing --dry-run   # 看要补什么
python batch.py prewarm --mode detail --scope missing             # 补缓存里缺详情的词
python batch.py prewarm --mode basic --scope neighbors --limit 50 # 往漫游图外铺新词
python batch.py prewarm --mode basic --mode deep --word 词 --word 词  # 指定词
```

- `--scope`：`missing`=缓存里缺该模式的词；`neighbors`=漫游图里提到但没走过的词（铺图）；
  `related`=配 `--word`，把那几棵树里出现过的每个词收进来（只配 `--mode detail` 用）。
- `--mode` 可重复，互不依赖的模式合成一次跑省时间。
- 预热结果 `data["src"]="prewarm"`，前端暂不展示该标记，但别删——区分来源有用。
- 校验不过会自动重掷一次，再不过就放弃并写 `data/abnormal.log`，不是错误，是设计。

## 会话模型直生成（零 API 费，你自己当生成器）

小批量补词（≤10 条）或烟测时首选这条：跳过 MiMo API，由当前会话的模型直接答卷。

```bash
python batch.py agent-prepare --mode basic --scope neighbors --limit 5
```

然后你（会话模型）就是答卷人，流程：

1. 读 `data/agent_in/todo-*.jsonl`，**逐条**按其 `system`+`user` 字段生成正文——
   那就是该词的真实提示词（已带口味偏好、已访问词表、上下文片段），不要自己重新发明格式；
2. 每行 `{"custom_id": "basic-0", "content": "<按该条提示词生成的原文>"}` 写进同目录答卷文件；
   注意校验下限要满足（parents≥1/children≥3/similar≥5，similar 里至少 2 个跨领域词，
   note≤15 字），一次生成 3~5 条是质量上限，多了注意力会摊薄；
3. 收卷：`python batch.py agent-merge todo-xxx.jsonl 答卷.jsonl`（文件名不给路径会自动到
   `data/agent_in/` 下找）。不过关的词会点名打印，重写 content 再收一轮；
4. 你写的内容也会被原样校验——parse_llm_json 容忍代码围栏，但格式和数量底线不豁免。

十几个词以上别用这条（上下文越滚越贵），改走 prewarm 在线并发。

## 离线批量（submit/poll/ingest）：只在用户开口时用

用户原话：批量"只适合工作、不急、省钱"的场景，交互工具宁可开套餐。**不要主动推荐
批量**；用户明确说"过夜跑/省钱/批量"时才走这条路。完整流程见 README「批量预热」
章节，要点：

- 控制台建的任务 API Key 查不到，结果文件下载后用 `ingest-file` 回填。
- 回填后的校验不过词进 `retry_items`，用 `submit --retry <batch_id>` 重掷。
- 平台只留结果 30 天，完成后尽快 ingest。

## 排障

- `data/abnormal.log` 一行一事：截断/空返回/绕路解析/校验不过。预热跑完扫一眼尾部的
  新行，向用户汇报"成功 N、异常 M 及原因分布"，别只报成功数。
- 校验下限（`app.py` 的 `_validate`）：漫游 parents≥1/children≥3/similar≥5；深挖≥3 维
  ≥8 条；详情≤300 字且以句读收尾。模型返回"合法但偷懒"的 JSON 会被打回重掷——
  如果某词反复失败，先看是不是它本身太生僻，而不是调低校验。
- 改代码时**不许绕过** `build_prompt` / `merge_into_cache` / `_validate` 这三个共用点：
  在线和批量两条路必须共享同一套拼装、合并、校验，这是本项目防走样的核心约定。

## 收尾

预热/回填结束后：`git status` 确认只有数据文件变更（正常，不提交）；向用户报告缓存
词数变化（前后各报一次数字）和 abnormal.log 新增条目摘要。
