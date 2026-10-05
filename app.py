"""关键词漫游器:给一个词,返回上级分类/下级分类/相邻词,人挑有意思的去 B 站搜视频。

用法:
    setx DEEPSEEK_API_KEY "sk-..."   # 或在 PowerShell 里 $env:DEEPSEEK_API_KEY="sk-..."
    python app.py                    # 打开 http://127.0.0.1:8765

数据:
    data/cache.json 保存漫游过的关键词图,查过的词不再请求 API(省钱 + 地图越滚越大)。

模块分层(2026-10-02 拆分):
    store.py  数据层:四份 JSON + abnormal.log 的读写、用户设置、合并语义
    llm.py    LLM 层:提示词/chat请求/解析/校验/build_prompt 流水线
    app.py    本文件:Flask 路由 + 启动(并作为 batch.py 的兼容导入入口)
"""
import json
import os
import time

import requests
from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from store import (
    AUTO_DETAIL_MODES,
    BASE_DIR,
    DETAIL_FAIL_LIMIT,
    DETAIL_LEN_CHARS,
    TEMP_ROAM,
    api_snapshot,
    clear_detail_fail,
    detail_fail_count,
    load_asks,
    load_cache,
    load_notes,
    load_settings,
    log_abnormal,
    merge_api_settings,
    merge_into_cache,
    record_detail_fail,
    save_asks,
    save_cache,
    save_notes,
    save_settings,
)
from llm import (
    ASK_SYSTEM_PROMPT,
    CHAT_SYSTEM_PROMPT,
    DEFAULT_FLAVOR,
    END_PUNCT,
    # 以下 build_prompt/_validate/parse_llm_json 路由不用,专为 batch.py 的
    # `from app import ...` 老入口保留——两条生成路的兼容导入入口不许断
    _validate,
    build_prompt,
    call_llm,
    chat,
    missing_key_hint,
    parse_llm_json,
    resolve_api_config,
)

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html", default_flavor=DEFAULT_FLAVOR)


@app.route("/sw.js")
def service_worker():
    """PWA 的 service worker 必须从根路径提供,否则作用域被限制在 /static/,
    而本应用的 start_url 是 /。Service-Worker-Allowed 头显式放开到整站。"""
    resp = send_from_directory(BASE_DIR / "static", "sw.js", mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"   # 让浏览器每次核对 SW 是否更新
    return resp


@app.route("/api/expand")
def expand():
    _missing = missing_key_hint(resolve_api_config())
    if _missing:
        # 自建/本地端点通常不需要 key,只在官方端点强制;端点/key/模型来自 ⚙设置或环境变量
        return jsonify({"error": _missing}), 500

    word = request.args.get("word", "").strip()
    if not word:
        return jsonify({"error": "缺少 word 参数"}), 400
    if len(word) > 30:
        return jsonify({"error": "词太长了"}), 400

    flavor = request.args.get("flavor", "").strip() or DEFAULT_FLAVOR
    mode = request.args.get("mode", "basic")
    if mode not in ("basic", "deep", "detail"):
        return jsonify({"error": "mode 只能是 basic / deep / detail"}), 400

    force = request.args.get("force") == "1"  # 🔄重写:无视缓存强制重新生成
    cache_only = request.args.get("cache_only") == "1"  # 🧭漫游思考:只要缓存,缓存没有就不生成(零花费)

    cache = load_cache()
    entry = cache.get(word) or {}
    word_exists = bool(entry)      # 注意别写成 entry is not None:entry 上面兜了 {} ,永远不是 None

    # 缓存命中:漫游看词条本身,深挖和详情看词条里嵌的对应字段(force=重写时跳过)
    if not force:
        hit = None
        if mode == "basic" and entry.get("parents"):
            hit = entry
        elif mode == "deep" and entry.get("deep"):
            hit = entry["deep"]
        elif mode == "detail" and entry.get("detail"):
            hit = {"word": word, "detail": entry["detail"]}
        if hit is not None:
            if entry.get("failed") and clear_detail_fail(cache, word):
                save_cache(cache)   # 数据已经生成出来了 → 把之前的失败记录清掉
            return jsonify({"cached": True, "data": hit})

    # 详情有个已知的恶性循环:死活生成不出的词会被"自动补详情"每次重新排队,白花钱且永远好不了。
    # 连续失败到上限就不再自动打,手动点详情/🔄重写(force)照旧可以再试。
    if mode == "detail" and not force and detail_fail_count(entry) >= DETAIL_FAIL_LIMIT:
        n = detail_fail_count(entry)
        return jsonify({"error": f"这个词的详情已连续 {n} 次生成失败(模型总说不完整),"
                                 f"自动补详情已跳过它;手动点 📖 或 🔄重写可以再试",
                        "skipped": True, "failed_count": n}), 409

    try:
        if cache_only:
            # 目录里没有漫游树(可能是"只有深挖",也可能压根没漫游过)。
            # 把这两件事分开告诉前端:前端才知道该不该挂「补深挖词详情」那个入口——
            # 深挖-only 的词照样有一整棵深挖树可以补详情,不该被当成"什么都没有"。
            return jsonify({
                "error": "没有可复用的漫游缓存(这个词还没漫游过,或旧缓存没存思维链)",
                "no_roam": True,
                "word_exists": word_exists,
                "has_deep": bool(entry.get("deep")),
            }), 404
        ctx = request.args.get("ctx", "").strip()[:600]
        data = call_llm(word, flavor, list(cache.keys()), mode=mode, ctx=ctx)
    except requests.RequestException as e:
        # 网络/端点问题不算"这个词不行",不记失败(换好 key 就该能跑)
        log_abnormal("API请求失败", word, str(e)[:200])
        return jsonify({"error": f"API 请求失败:{e}"}), 502
    except (json.JSONDecodeError, AssertionError, ValueError) as e:
        # 模型出来了但不过关(腰斩/超长/JSON 崩)→ 记账,连续几次就不再自动重试
        log_abnormal("生成失败(重试耗尽或校验不过)", word, str(e)[:200])
        n = record_detail_fail(cache, word) if mode == "detail" else 0
        if n:
            save_cache(cache)
        extra = f"(第 {n} 次失败,再 {max(0, DETAIL_FAIL_LIMIT - n)} 次自动补详情就不碰它了)" if n else ""
        return jsonify({"error": f"模型返回解析失败:{e}{extra}"}), 502

    merge_into_cache(cache, word, mode, data, flavor)  # 合并语义与批量回填共用
    save_cache(cache)
    return jsonify({"cached": False, "data": data})


@app.route("/api/ask")
def ask():
    """详情划词后的追问:带上下文的 150 字快答,按 词+问题 缓存。"""
    word = request.args.get("word", "").strip()
    question = request.args.get("q", "").strip()
    context = request.args.get("ctx", "").strip()[:600]
    if not question:
        return jsonify({"error": "问题不能为空"}), 400
    if len(question) > 100:
        return jsonify({"error": "问题太长了,100 字以内"}), 400

    asks = load_asks()
    key = f"{word}:::{question}"
    if key in asks:
        return jsonify({"cached": True, "data": asks[key]})

    _missing = missing_key_hint(resolve_api_config())
    if _missing:
        return jsonify({"error": _missing}), 500

    user_msg = f"中心词:{word or '(无)'}\n正在阅读的介绍:{context or '(无)'}\n我的问题:{question}"
    last_err: Exception = ValueError("未执行")
    answer = ""
    for _attempt in range(2):  # 与对话同款:腰斩(半句话)重掷一次,宁可不答不上屏半截
        try:
            data, _reasoning = chat(ASK_SYSTEM_PROMPT, user_msg, temperature=0.7)  # 追问求准,温度降回来
            answer = data.get("answer")
            assert isinstance(answer, str) and answer.strip(), "模型返回缺少 answer"
            assert len(answer) <= 200, f"回答超长({len(answer)}字)"
            if not answer.rstrip().endswith(END_PUNCT):
                log_abnormal("追问疑似腰斩", f"{word}::{question[:30]}", f"结尾:{answer[-40:]!r}")
                raise ValueError("回答话说一半,重掷一次")
            break
        except (requests.RequestException, json.JSONDecodeError, AssertionError, ValueError) as e:
            last_err = e
            answer = ""
    else:
        log_abnormal("回答生成失败(ask)", f"{word}::{question[:30]}", str(last_err)[:200])
        return jsonify({"error": f"回答生成失败:{last_err}"}), 502

    entry = {"word": word, "question": question, "answer": data["answer"], "time": int(time.time())}
    asks[key] = entry
    save_asks(asks)
    return jsonify({"cached": False, "data": entry})


@app.route("/api/chat", methods=["POST"])
def chat_api():
    """底部对话条:绑在当前词上的多轮追问。
    首轮吃 asks 单轮缓存(划词追问问过同样的就不花钱);对话本身不持久化(会话级);
    上下文带最近 6 轮,回答封顶 300 字,超长自动重掷一次。"""
    _missing = missing_key_hint(resolve_api_config())
    if _missing:
        return jsonify({"error": _missing}), 500

    body = request.get_json(silent=True) or {}
    word = str(body.get("word") or "").strip()[:30]
    q = str(body.get("q") or "").strip()
    context = str(body.get("ctx") or "")[:600]
    if not q:
        return jsonify({"error": "问题不能为空"}), 400
    if len(q) > 100:
        return jsonify({"error": "问题太长了,100 字以内"}), 400
    history = [
        {"role": "user" if m.get("role") == "user" else "assistant",
         "content": str(m.get("content") or "")[:400]}
        for m in (body.get("history") or [])[-12:]
        if isinstance(m, dict) and str(m.get("content") or "").strip()
    ]

    asks = load_asks()
    key = f"{word}:::{q}"
    regen = body.get("regen") is True  # 🔄重新回答:跳过 asks 缓存,新答案会覆盖回同一条
    if not history and not regen and key in asks:  # 只有无上下文的首轮吃缓存:带语境的回答不该覆盖原答案
        return jsonify({"cached": True, "data": asks[key]})

    user_msg = f"中心词:{word or '(无)'}\n正在阅读的介绍:{context or '(无)'}\n我的问题:{q}"
    last_err: Exception = ValueError("未执行")
    answer = ""
    for _attempt in range(2):  # 300 字封顶,超长当废品重掷
        try:
            data, _reasoning = chat(CHAT_SYSTEM_PROMPT, user_msg, temperature=0.7, extra_msgs=history)
            answer = data.get("answer")
            assert isinstance(answer, str) and answer.strip(), "模型返回缺少 answer"
            assert len(answer) <= 350, f"回答超长({len(answer)}字)"
            if not answer.rstrip().endswith(END_PUNCT):
                # 与详情同款腰斩检测:思维链吃掉 max_tokens 预算时,正文会在半句话被掐
                log_abnormal("对话疑似腰斩", f"{word}::{q[:30]}", f"结尾:{answer[-40:]!r}")
                raise ValueError("回答话说一半,重掷一次")
            break
        except (requests.RequestException, json.JSONDecodeError, AssertionError, ValueError) as e:
            last_err = e
            answer = ""
    else:
        log_abnormal("对话生成失败", f"{word}::{q[:30]}", str(last_err)[:200])
        return jsonify({"error": f"对话生成失败:{last_err}"}), 502

    entry = {"word": word, "question": q, "answer": answer.strip(), "time": int(time.time())}
    if not history:  # 首轮问答顺手进 asks.json,划词追问同问题直接命中
        asks[key] = entry
        save_asks(asks)
    return jsonify({"cached": False, "data": entry})


@app.route("/api/note", methods=["GET", "POST"])
def note_api():
    """📝绑在词上的手写笔记:一词一条,自动保存,重启不丢(data/notes.json)。
    POST 清空文本 = 删除该词的笔记,不留空条目。"""
    if request.method == "GET":
        word = request.args.get("word", "").strip()
        return jsonify({"text": (load_notes().get(word) or {}).get("text", "")})
    body = request.get_json(silent=True) or {}
    word = str(body.get("word") or "").strip()[:30]
    text = str(body.get("text") or "")[:5000]
    if not word:
        return jsonify({"error": "缺少 word 参数"}), 400
    notes = load_notes()
    if text.strip():
        notes[word] = {"text": text, "time": int(time.time())}
    else:
        notes.pop(word, None)
    save_notes(notes)
    return jsonify({"ok": True, "empty": not text.strip()})


@app.route("/api/tree-words")
def tree_words():
    """📚一键补详情的原料:这个词的漫游树+深挖树里出现过的词(去重),
    标注谁缺详情、谁在黑名单。词表只是清单,生成本体仍走 /api/expand。"""
    word = request.args.get("word", "").strip()
    if not word:
        return jsonify({"error": "缺少 word 参数"}), 400
    cache = load_cache()
    d = cache.get(word) or {}
    black = set(load_settings()["blacklist"])
    seen, items = set(), []

    def add(w: str, grp: str) -> None:
        w = str(w or "").strip()
        if not w or w in seen:
            return
        seen.add(w)
        ent = cache.get(w) or {}
        fails = detail_fail_count(ent)
        items.append({
            "word": w, "grp": grp,
            "has_detail": bool(ent.get("detail")),
            "black": w in black,
            # 连续失败到上限:自动补详情不再碰它(前端也据此跳过,别白花钱)
            "skipped": not ent.get("detail") and fails >= DETAIL_FAIL_LIMIT,
            "failed_count": fails,
        })

    for grp in ("parents", "children", "similar"):
        for it in d.get(grp) or []:
            add(it.get("word"), "roam")
    for dim in (d.get("deep") or {}).get("dimensions") or []:
        for it in dim.get("items") or []:
            add(it.get("word"), "deep")
    return jsonify({"count": len(items), "items": items})


@app.route("/api/deep-words")
def deep_words():
    """🔍补深挖词详情:把「深挖树」里还缺详情的词列出来。

    不带 word → 扫遍缓存里所有有深挖的词(挑词用,响应只含缺的那些,通常十几个);
    带 word   → 只扫这一棵树的深挖维度。

    注意:前端按钮走的是 /api/tree-words(它把漫游树和深挖树一起给出来,好支持
    「整树补详情 / 只补深挖词」两种口径)。这个接口是同一口径的"只挑深挖词"精简版,
    两边挑出的词经比对完全一致,给批量脚本用。
    """
    word = request.args.get("word", "").strip()
    cache = load_cache()
    black = set(load_settings()["blacklist"])

    if word:
        trees = [word] if (cache.get(word) or {}).get("deep") else []
    else:
        trees = [w for w, d in cache.items() if d.get("deep")]

    refs, need, seen, skipped = set(), [], set(), 0
    for t in trees:
        deep = (cache.get(t) or {}).get("deep") or {}
        for dim in deep.get("dimensions") or []:
            for it in dim.get("items") or []:
                nw = str((it or {}).get("word") or "").strip()
                if not nw:
                    continue
                refs.add(nw)
                ent = cache.get(nw) or {}
                if ent.get("detail") or nw in black or nw in seen:
                    continue
                seen.add(nw)
                if detail_fail_count(ent) >= DETAIL_FAIL_LIMIT:
                    skipped += 1        # 反复生成不出来的词,不进清单(前端另有"重试"出口)
                    continue
                need.append(nw)

    return jsonify({
        "scope": word or "(全部深挖树)",
        "trees": len(trees),
        "refs": len(refs),
        "count": len(need),
        "skipped": skipped,
        "missing": need,
    })


@app.route("/api/export")
def export_data():
    """足迹导出:cache.json(+asks.json)打包下载。json=完整备份(可再导回),md=可读词表。
    what=notes 时只导笔记(独立成 md/文件)。删缓存=地图清零,这里是后悔药。"""
    fmt = request.args.get("format", "json")
    what = request.args.get("what", "all")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    cache = load_cache()
    notes = load_notes()

    if what == "notes":   # 仅笔记:md=可读合集,json=原始数据
        if fmt == "md":
            lines = [
                "# 关键词漫游笔记",
                "",
                f"> 导出时间:{time.strftime('%Y-%m-%d %H:%M:%S')} · 共 {len(notes)} 条 · 关键词漫游器",
            ]
            for w, n in sorted(notes.items(), key=lambda kv: kv[1].get("time") or 0):
                lines.append(f"\n## {w}")
                if n.get("time"):
                    lines.append(f"*{time.strftime('%Y-%m-%d %H:%M', time.localtime(n['time']))}*")
                lines.append("")
                lines.append(n.get("text", "").strip())
            return Response(
                "\n".join(lines), mimetype="text/markdown; charset=utf-8",
                headers={"Content-Disposition": f"attachment; filename=roam-notes-{stamp}.md"},
            )
        return Response(
            json.dumps({"exported_at": int(time.time()), "format": "roam-notes-v1", "notes": notes},
                       ensure_ascii=False, indent=1),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename=roam-notes-{stamp}.json"},
        )

    if fmt == "md":
        lines = [
            "# 关键词漫游足迹",
            "",
            f"> 导出时间:{time.strftime('%Y-%m-%d %H:%M:%S')} · 共 {len(cache)} 词 · 关键词漫游器",
        ]
        for w, d in sorted(cache.items(), key=lambda kv: kv[1].get("time") or 0):
            lines.append(f"\n## {w}")
            if d.get("time"):
                lines.append(f"*{time.strftime('%Y-%m-%d %H:%M', time.localtime(d['time']))}"
                             f"{(' · ' + d['flavor']) if d.get('flavor') else ''}*")
            for title, grp in (("⬆ 上级", "parents"), ("⬇ 下级", "children"), ("↔ 相邻", "similar")):
                items = d.get(grp) or []
                if items:
                    lines.append(f"- **{title}**:" + "、".join(
                        f"{it.get('word')}({it.get('note')})" if it.get("note") else str(it.get("word"))
                        for it in items))
            if d.get("detail"):
                lines.append(f"- **📖 详情**:{d['detail']}")
            if w in notes and notes[w].get("text", "").strip():
                lines.append(f"- **📝 笔记**:{notes[w]['text'].strip()}")
            for dim in (d.get("deep") or {}).get("dimensions") or []:
                its = dim.get("items") or []
                if its:
                    lines.append(f"- **🔍 {dim.get('name', '?')}**:" + "、".join(
                        f"{it.get('word')}({it.get('note')})" if it.get("note") else str(it.get("word"))
                        for it in its))
        asks = load_asks()
        if asks:
            lines.append(f"\n---\n\n## 附录:缓存的追问({len(asks)} 条)")
            for a in sorted(asks.values(), key=lambda x: x.get("time") or 0):
                lines.append(f"- **{a.get('word')}**:{a.get('question')} → {a.get('answer')}")
        md = "\n".join(lines)
        return Response(
            md, mimetype="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=roam-footprint-{stamp}.md"},
        )
    payload = {"exported_at": int(time.time()), "format": "roam-backup-v1", "cache": cache, "asks": load_asks(), "notes": notes}
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=1), mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=roam-backup-{stamp}.json"},
    )


@app.route("/api/settings", methods=["GET", "POST"])
def settings_api():
    """⚙设置面板读写。即改即生效(下一次生成起),缓存里的旧数据不动。
    POST 部分更新:只校验并落盘传来的键,没传的保持原样。
    api.key 特殊:GET 永不回原文(只回 has_key + 掩码预览);POST 空串=别动。"""
    if request.method == "GET":
        s = load_settings()
        s["api"] = api_snapshot(s)
        return jsonify(s)
    body = request.get_json(silent=True) or {}
    s = load_settings()
    if "detail_len" in body:
        if body["detail_len"] not in DETAIL_LEN_CHARS:
            return jsonify({"error": "detail_len 只能是 短/标准/长"}), 400
        s["detail_len"] = body["detail_len"]
    if "temp_style" in body:
        if body["temp_style"] not in TEMP_ROAM:
            return jsonify({"error": "temp_style 只能是 稳/标准/抽风"}), 400
        s["temp_style"] = body["temp_style"]
    if "auto_detail" in body:
        if body["auto_detail"] not in AUTO_DETAIL_MODES:
            return jsonify({"error": "auto_detail 只能是 off/smart/all"}), 400
        s["auto_detail"] = body["auto_detail"]
    if "flavors" in body:
        if not isinstance(body["flavors"], list):
            return jsonify({"error": "flavors 要是字符串列表"}), 400
        s["flavors"] = [str(f).strip()[:60] for f in body["flavors"] if str(f).strip()][:20]
    if "blacklist" in body:
        if not isinstance(body["blacklist"], list):
            return jsonify({"error": "blacklist 要是字符串列表"}), 400
        s["blacklist"] = [str(w).strip()[:30] for w in body["blacklist"] if str(w).strip()][:200]
    if "api" in body:
        if not isinstance(body["api"], dict):
            return jsonify({"error": "api 要是对象"}), 400
        s["api"] = merge_api_settings(s.get("api"), body["api"])
    save_settings(s)
    resp = dict(s)
    resp["api"] = api_snapshot(s)
    return jsonify(resp)


@app.route("/api/test-conn", methods=["POST"])
def test_conn():
    """模型接口连通性诊断:用当前(或传入的)配置打一次 /models,把失败原因分类。
    这个接口跑在服务端,所以它失败=端点/key/网络的问题;若这里通了而浏览器版不通,
    那就是 CORS(浏览器直连被拦)——所以响应里专门给一句 browser_hint。"""
    body = request.get_json(silent=True) or {}
    s = load_settings()
    if isinstance(body.get("api"), dict):
        s = dict(s)
        s["api"] = merge_api_settings(s.get("api"), body["api"])
    cfg = resolve_api_config(s)
    base = cfg["base_url"]
    hint = missing_key_hint(cfg)

    started = time.time()
    models, status_code, err = None, None, None
    try:
        r = requests.get(f"{base}/models",
                         headers={"Authorization": f"Bearer {cfg['api_key']}"}, timeout=15)
        status_code = r.status_code
        if r.status_code == 200:
            try:
                data = r.json().get("data") or []
                models = [str((m or {}).get("id") or "") for m in data if (m or {}).get("id")]
            except (ValueError, AttributeError):
                models = []
        else:
            err = (r.text or "")[:300]
    except Exception as e:
        err = f"{type(e).__name__}: {e}"

    latency = int((time.time() - started) * 1000)
    reason = None
    if models is not None:
        pass                                   # 通了
    elif hint:
        reason = "missing_key"
    elif err and "SSLError" in err:
        reason = "tls"
    elif err and "ConnectionError" in err:
        reason = "connection"                  # 域名不存在 / 拒绝连接 / 代理
    elif err and "Timeout" in err:
        reason = "timeout"
    elif status_code == 401:
        reason = "auth"
    elif status_code == 403:
        reason = "forbidden"
    elif status_code == 404:
        reason = "not_found"
    elif status_code == 429:
        reason = "rate_limit"
    elif status_code and status_code >= 500:
        reason = "server"
    else:
        reason = "unknown"

    model_listed = None
    if models is not None and cfg["model"]:
        model_listed = cfg["model"] in models

    hints = {
        "missing_key": "还没填 API Key。本地端点(如 Ollama)一般不用填。",
        "tls": "TLS/证书握手失败:检查 BASE_URL 是不是 https、或公司代理拦了证书。",
        "connection": f"连不上 {base} —— 域名/端口写错、断网,或该端点不对外。",
        "timeout": "连接超时:端点不可达,或网络太慢。",
        "auth": "Key 无效或已过期(401)。确认复制完整、没夹空格。",
        "forbidden": "被拒绝(403):该 key 没有访问此端点的权限,或来源被限制。",
        "not_found": "路径不对(404):BASE_URL 通常要到 /v1 这一层,检查末尾路径。",
        "rate_limit": "限流(429):稍等再试,或降低并发。",
        "server": f"端点报错({status_code}):对方服务的问题,不是你的配置。",
        "unknown": "没识别出具体原因,把下面的原始信息发给我。",
    }
    result = {
        "ok": models is not None,
        "reason": reason,
        "hint": hints.get(reason),
        "raw_error": (err or "")[:300],
        "status_code": status_code,
        "latency_ms": latency,
        "base_url": base,
        "model": cfg["model"],
        "max_tokens": cfg["max_tokens"],
        "key_from": cfg["key_from"],
        "models": (models or [])[:200],
        "model_listed": model_listed,
        "browser_hint": ("浏览器版还要看端点的 CORS:若 API 能通但网页版连不上,"
                         "就是这个端点不允许跨域,换端点或改用桌面版。"),
    }
    return jsonify(result)


@app.route("/api/graph")
def graph():
    """足迹地图数据:节点=缓存词,边=两端都在缓存的漫游/深挖关系,
    frontier=被提及但还没走到的词(挂在其首个出处的缓存词上,前端画成空心前沿)。"""
    cache = load_cache()
    nodes, edges, pairs = [], [], set()
    f_seen = {}
    for w, d in cache.items():
        feats = []
        if d.get("parents"):
            feats.append("roam")
        if d.get("deep"):
            feats.append("deep")
        if d.get("detail"):
            feats.append("detail")
        nodes.append({"word": w, "feats": feats, "time": d.get("time") or 0})
        rels = [(g, d.get(g) or []) for g in ("parents", "children", "similar")]
        deep = d.get("deep") or {}
        rels.append(("deep", [it for dim in deep.get("dimensions") or [] for it in dim.get("items") or []]))
        for rel, items in rels:
            for it in items:
                nw = str((it or {}).get("word") or "").strip()
                if not nw or nw == w:
                    continue
                if nw in cache:
                    pair = tuple(sorted((w, nw)))
                    if pair not in pairs:
                        pairs.add(pair)
                        edges.append({"a": w, "b": nw, "rel": rel})
                elif nw not in f_seen:
                    f_seen[nw] = w
    frontier = [{"word": nw, "anchor": a} for nw, a in f_seen.items()]
    return jsonify({"nodes": nodes, "edges": edges, "frontier": frontier})


@app.route("/api/cache")
def cache_info():
    """足迹:已漫游过的词,按最近漫游排序,带功能标记(前端分类筛选用)。
    failed 一起回:前端据此把"反复生成不出详情"的词直接排掉,连那一次 409 都不用发。"""
    cache = load_cache()
    words = []
    for w, d in cache.items():
        feats = []
        if d.get("parents"):
            feats.append("roam")
        if d.get("deep"):
            feats.append("deep")
        if d.get("detail"):
            feats.append("detail")
        words.append({"word": w, "time": d.get("time") or 0, "feats": feats,
                      "failed": detail_fail_count(d)})
    words.sort(key=lambda x: x["time"], reverse=True)
    return jsonify({"count": len(words), "words": words})


if __name__ == "__main__":
    port = int(os.environ.get("ROAM_PORT", "8765"))
    _cfg = resolve_api_config()
    print(f"关键词漫游器:http://127.0.0.1:{port}   (模型:{_cfg['model']}  端点:{_cfg['base_url']}  key来自:{_cfg['key_from']})")
    app.run(host="127.0.0.1", port=port, debug=False)
