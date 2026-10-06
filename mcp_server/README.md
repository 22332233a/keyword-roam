# keyword-roam MCP 包装器

把漫游器的 HTTP API 包成 MCP tools，让任意 MCP 客户端（N.E.K.O 的 mcp_adapter、
Claude Desktop、Cherry Studio…）调用漫游/追问能力。
**keyword-roam 本体零改动**——本服务只做转发，缓存、校验、重掷、黑名单防线全部留在原地。

## Tools

| tool | 作用 | 花费 |
|---|---|---|
| `list_visited` | 列出全部到访词（带 roam/deep/detail 标记），按最近排序 | 零 |
| `get_cached_detail` | 读某词已缓存的 150 字详情；没缓存明说，不触发生成 | 零 |
| `roam_word` | 漫游生成（basic=词树 / deep=深挖维度） | 未命中缓存会调 LLM，约 1 分钟 |
| `ask_about` | 对某词追问（≤100 字问 → ≤200 字答），同问有缓存 | 新问题调 LLM |

## 启动前提

漫游器本体先跑起来（`python app.py`，默认 `http://127.0.0.1:8765`；
可用环境变量 `KEYWORD_ROAM_API` 改指向）。

## 本地测试

```bash
.venv/Scripts/python.exe test_client.py
```

（拉起 server、列出 tools、实调 list_visited 和 get_cached_detail。）

## 接入 N.E.K.O

插件页 → MCP Adapter → 面板 → JSON 导入：

```json
{
  "name": "keyword-roam",
  "transport": "stdio",
  "command": "<本仓库绝对路径>/mcp_server/.venv/Scripts/python.exe",
  "args": ["<本仓库绝对路径>/mcp_server/server.py"],
  "env": { "KEYWORD_ROAM_API": "http://127.0.0.1:8765" },
  "enabled": true,
  "auto_connect": true
}
```

## 环境重建

`.venv/` 不进 git。重装：

```bash
uv venv .venv
uv pip install --python .venv "mcp<2" requests --index-url https://mirrors.aliyun.com/pypi/simple/
```

（`mcp<2`：2.x 把 FastMCP 改名为 MCPServer，v1 API 与各教程/videoread 一致。）
