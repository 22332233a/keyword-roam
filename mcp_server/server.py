# -*- coding: utf-8 -*-
"""keyword-roam 的 MCP 包装器:把漫游器的 HTTP API 包成 MCP tools。

设计原则:keyword-roam 本体零改动——本服务只做转发,
缓存、校验、重掷、黑名单等防线全部留在原地。MCP 客户端
(如 N.E.K.O 的 mcp_adapter)通过 stdio 拉起本服务,即可让
AI 助手调用"查足迹/读缓存详情/漫游生成/追问"四种能力。

前置:keyword-roam 已启动(app.py,默认 http://127.0.0.1:8765),
可用环境变量 KEYWORD_ROAM_API 改指向。
"""
import os

import requests
from mcp.server.fastmcp import FastMCP

BASE = os.environ.get("KEYWORD_ROAM_API", "http://127.0.0.1:8765").rstrip("/")

mcp = FastMCP(
    "keyword-roam",
    instructions=(
        "关键词漫游器的包装:先 list_visited 看足迹,再决定读缓存详情"
        "(零花费)还是漫游生成(会调 LLM,可能耗时一分钟)。"
        "对已读的词可以 ask_about 追问。"
    ),
)


def _get(path: str, timeout: int = 60, **params) -> dict:
    """转发 GET 请求。HTTP 错误状态也带 JSON 错误体(如 cache_only 未命中 404、
    详情连续失败 409),一律解析透传,由各 tool 按自己的语义处理;网络层异常
    (漫游器没启动等)兜底成 error 字段,不让异常裸穿到 LLM 面前。"""
    try:
        resp = requests.get(f"{BASE}{path}", params=params, timeout=timeout)
    except requests.RequestException as e:
        return {"error": f"连不上漫游器({BASE}):{e.__class__.__name__}"}
    try:
        return resp.json()
    except ValueError:
        return {"error": f"漫游器返回非 JSON(HTTP {resp.status_code})"}


@mcp.tool()
def list_visited() -> str:
    """列出漫游器里所有到访过的词(带功能标记 roam=漫游过 deep=深挖过 detail=读过详情),按最近排序取前 30。决定漫游什么之前先看这个。"""
    data = _get("/api/cache")
    words = sorted(data.get("words", []), key=lambda w: w.get("time") or 0, reverse=True)
    lines = [f"共 {data.get('count', len(words))} 词,最近 30 个:"]
    for w in words[:30]:
        feats = "+".join(w.get("feats") or []) or "仅路过"
        lines.append(f"- {w['word']}({feats})")
    return "\n".join(lines)


@mcp.tool()
def get_cached_detail(word: str) -> str:
    """读取某个词已缓存的详情(150 字小传),只读缓存、零花费;没有缓存会明说,不会触发生成。"""
    data = _get("/api/expand", word=word, mode="detail", cache_only="1")
    entry = data.get("data") or {}   # expand 的返回是 {cached, data:{...}} 嵌套
    if data.get("error") or not entry.get("detail"):
        return f"「{word}」还没有缓存的详情。"
    return f"「{entry.get('word', word)}」:{entry['detail']}"


@mcp.tool()
def roam_word(word: str, mode: str = "basic") -> str:
    """漫游一个词:basic=生成关联词树(上级/下级/相邻),deep=生成深挖维度。注意:缓存未命中时会真实调用 LLM,可能耗时一分钟并有 API 花费。"""
    if mode not in ("basic", "deep"):
        return "mode 只能是 basic(关联词树)或 deep(深挖维度)"
    data = _get("/api/expand", word=word, mode=mode, timeout=180)
    if data.get("error"):
        return f"漫游失败:{data['error']}"
    entry = data.get("data") or {}   # 嵌套:真身在 data 字段里
    parts = [f"「{entry.get('word', word)}」的漫游结果:"]
    for grp, title in (("parents", "↑ 上级"), ("children", "↓ 下级"), ("similar", "↔ 相邻")):
        items = entry.get(grp) or []
        if items:
            parts.append(f"{title}:" + "、".join(i.get("word", "") for i in items))
    for dim in (entry.get("deep") or {}).get("dimensions") or []:
        items = dim.get("items") or []
        if items:
            parts.append(f"[{dim.get('title', '深挖')}]" + "、".join(i.get("word", "") for i in items))
    return "\n".join(parts)


@mcp.tool()
def ask_about(word: str, question: str) -> str:
    """对某个词提出追问(100 字以内),得到 200 字以内的快答。相同问题命中缓存零花费;新问题会调用 LLM。"""
    if len(question) > 100:
        return "问题太长了,100 字以内。"
    data = _get("/api/ask", word=word, q=question, timeout=120)
    if data.get("error"):
        return f"追问失败:{data['error']}"
    tag = "(缓存)" if data.get("cached") else ""
    entry = data.get("data") or {}
    return f"{entry.get('answer', '')}{tag}"


if __name__ == "__main__":
    mcp.run()   # stdio 传输:MCP 客户端以子进程拉起,经 stdin/stdout 通信
