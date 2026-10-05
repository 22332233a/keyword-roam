"""缓存预热:给 data/cache.json 铺图,两条路任选。

在线并发(快,全价,推荐):直接打现有 /chat/completions,平台限流 RPM=100/TPM=10M 内随便并发,
提示词/校验/合并与在线完全同源;失败重跑同一句即可,按 scope 挑词只挑还缺的。
    python batch.py prewarm --mode detail --scope missing              # 缺详情的全补上
    python batch.py prewarm --mode basic --mode deep --word A --word B --concurrency 8

离线批量(便宜,要排队,适合几百上千条过夜跑)。三道工序:
    python batch.py submit --mode detail --scope missing      # 挑词→生成 JSONL→上传→建任务
    python batch.py poll [--watch 300]                        # 查进度,到终态提示回填
    python batch.py ingest <batch_id>                         # 下结果→校验→并进 cache.json

会话模型直生成(零 API 费,适合补几个词/烟测):出题文件给对话里的模型答卷,收卷校验与两条路同源。
    python batch.py agent-prepare --mode basic --scope neighbors --limit 5
    # 模型按 data/agent_in/todo-*.jsonl 里每条的 system+user 生成正文,写成答卷 jsonl({custom_id, content})
    python batch.py agent-merge todo-xxx.jsonl 答卷.jsonl

主题式铺图(漫游→深挖→详情,详情依赖前两轮的结果,必须等 ingest 完再发):
    python batch.py submit --mode basic --word A --word B    # 第一轮:这几棵树的漫游词
    python batch.py submit --mode deep  --word A --word B    # 第一轮:同一批词深挖
    python batch.py poll && python batch.py ingest <任务号>   # 两个任务都回填
    python batch.py submit --mode detail --scope related --word A --word B --word 大语言模型
    # scope=related 把那几棵树(漫游+深挖)里出现过的每个词都收进来补详情,已有详情的自动跳过

先小批量烟测(生成的 JSONL 与官方模板 data/demo.jsonl 同构):
    python batch.py submit --mode detail --word 咖啡豆 --word 猫 --dry-run   # 只出文件,不上传
    python batch.py submit --mode detail --word 咖啡豆 --word 猫             # 真提交

环境变量:
    ROAM_BATCH_BASE_URL  批量推理 Base URL(仅离线路径用,从批量推理页面抄,形如 https://batch-api-<region>.xiaomimimo.com)
    LLM_API_KEY / DEEPSEEK_API_KEY、LLM_MODEL / DEEPSEEK_MODEL、ROAM_MAX_TOKENS 两条路共用

最长等待时间(仅离线批量):控制台那个框可填 1~14 天(默认 7 天,创建后不可改),对应 --days N;--window 可原样透传。

页面手动上传的路子(不配 Base URL 也能走):把 submit --dry-run 生成的 jsonl 拖进平台页面,
跑完下载结果文件,再用 ingest-file 回填——靠同名 .map.json 把 custom_id 对回词。
    python batch.py ingest-file data/batch_in/xxx.jsonl 下载的output.jsonl [--errors 下载的errors.jsonl]

校验不过的词(详情腰斩等)记进任务的 retry_items(对应在线"校验不过自动重掷一次"),用
    python batch.py submit --retry <batch_id>
再掷一轮。平台只留数据 30 天,任务完成尽快 ingest。
"""
import argparse
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from llm import missing_key_hint as missing_hint
from app import (
    BASE_DIR,
    DEFAULT_FLAVOR,
    _validate,
    build_prompt,
    call_llm,
    load_cache,
    log_abnormal,
    merge_into_cache,
    parse_llm_json,
    resolve_api_config,   # 端点/key/模型跟着 ⚙设置走(环境变量兜底),不再从 app 取旧常量
    save_cache,
)

JOBS_FILE = BASE_DIR / "data" / "batch_jobs.json"
IN_DIR = BASE_DIR / "data" / "batch_in"
OUT_DIR = BASE_DIR / "data" / "batch_out"
AGENT_DIR = BASE_DIR / "data" / "agent_in"

BATCH_BASE = (os.environ.get("ROAM_BATCH_BASE_URL") or "").rstrip("/")
if BATCH_BASE.endswith("/v1"):  # 抄来的 Base URL 常带 /v1,统一去掉,拼路径时再加
    BATCH_BASE = BATCH_BASE[:-3]

ENDPOINT = "/v1/chat/completions"
TERMINAL = ("completed", "failed", "cancelled", "expired")
# 最长等待时间:控制台默认 7 天(可填 1~14 天,创建后不可改)。文档只给了 "24h" 示例,
# 这里按小时换算提交(7 天 = 168h);若平台不认,用 --window 24h 原样试。
DEFAULT_WINDOW = "168h"
MAX_REQUESTS = 50000          # 平台限制:单批 ≤ 50,000 请求
MAX_FILE_BYTES = 128 * 1024 * 1024  # 平台限制:单文件 ≤ 128MB


def _window(args) -> str:
    """--days 按天填(对齐控制台那个 1~14 天的输入框),--window 原样透传。"""
    if args.days and args.window:
        raise SystemExit("--days 和 --window 二选一")
    if args.days:
        if not 1 <= args.days <= 14:
            raise SystemExit("--days 只能填 1~14(平台限制),你填的是 %d" % args.days)
        return f"{args.days * 24}h"
    return args.window or DEFAULT_WINDOW


def _need_base() -> None:
    if not BATCH_BASE:
        raise SystemExit(
            "未设置 ROAM_BATCH_BASE_URL(批量推理页面的 Base URL),"
            "形如 https://batch-api-<region>.xiaomimimo.com"
        )
    if not resolve_api_config()["api_key"]:
        raise SystemExit("未配置 API Key:到 ⚙设置 →「模型接口」填,或设 LLM_API_KEY / DEEPSEEK_API_KEY")


def _req(method: str, path: str, timeout: int = 120, **kw):
    r = requests.request(
        method,
        BATCH_BASE + path,
        headers={"Authorization": f"Bearer {resolve_api_config()['api_key']}"},
        timeout=timeout,
        **kw,
    )
    if r.status_code >= 400:
        raise SystemExit(f"HTTP {r.status_code} {BATCH_BASE + path}\n{r.text[:500]}")
    return r


def load_jobs() -> dict:
    if JOBS_FILE.exists():
        return json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    return {}


def save_jobs(jobs: dict) -> None:
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    JOBS_FILE.write_text(json.dumps(jobs, ensure_ascii=False, indent=1), encoding="utf-8")


def pick_targets(mode: str, scope: str, words: list, limit: int, flavor_arg: str) -> tuple:
    """挑出要批量生成的词。scope=missing 挑缓存里缺该模式的,neighbors 挑漫游图里没走过的。
    返回 (items, visited):items 带 custom_id,visited 是发起时的已访问快照(进提示词)。"""
    cache = load_cache()
    visited = list(cache.keys())
    items = []

    def pack(w: str, ctx: str = "") -> None:
        entry = cache.get(w) or {}
        items.append({
            "word": w,
            "mode": mode,
            "flavor": entry.get("flavor") or flavor_arg or DEFAULT_FLAVOR,
            "ctx": ctx,
        })

    if scope == "related":
        # 以 --word 给的词为根,把这几棵树里出现过的每个词都收进来(树来自已漫游/已深挖的缓存)。
        # 注意要排在 if words 前面:这个作用域本身就是靠 --word 指定根词的。
        roots = [str(w).strip() for w in words if str(w).strip()]
        if not roots:
            raise SystemExit("--scope related 要配 --word 指定根词(树从这些词身上找)")
        pool, seen = [], set()

        def add(w, ctx: str = "") -> None:
            w = str(w).strip()
            if w and w not in seen:
                seen.add(w)
                pool.append((w, ctx))

        for r in roots:
            add(r)
            d = cache.get(r) or {}
            for grp in ("parents", "children", "similar"):
                for it in d.get(grp) or []:
                    add(it.get("word"), f"{r}({it.get('note', '')})")
            for dim in (d.get("deep") or {}).get("dimensions") or []:
                for it in dim.get("items") or []:
                    add(it.get("word"), f"{r}-{dim.get('name', '')}({it.get('note', '')})")
        for w, ctx in pool:
            if not (cache.get(w) or {}).get("detail"):  # 已有详情的跳过,不重复花钱
                pack(w, ctx=ctx)
    elif words:
        for w in words:
            w = str(w).strip()
            if w:
                pack(w)
    elif scope == "missing":
        key = {"basic": "parents", "deep": "deep", "detail": "detail"}[mode]
        for w, d in cache.items():
            if not d.get(key):
                pack(w)
    elif scope == "neighbors":
        seen = set()
        for w, d in cache.items():
            for grp in ("parents", "children", "similar"):
                for it in d.get(grp) or []:
                    nw = str(it.get("word") or "").strip()
                    if not nw or nw in cache or nw in seen:
                        continue
                    seen.add(nw)
                    pack(nw, ctx=f"{w}({it.get('note', '')})")

    items = items[:limit]
    for i, it in enumerate(items):
        it["custom_id"] = f"{mode}-{i}"
    return items, visited


def build_line(item: dict, visited: list) -> dict:
    """一条 JSONL:结构与 data/demo.jsonl 完全同构,body 与在线请求同一套拼装。"""
    system, user_msg, temperature = build_prompt(
        item["word"], item["flavor"], visited, mode=item["mode"], ctx=item.get("ctx", "")
    )
    cfg = resolve_api_config()   # 模型/上限跟着 ⚙设置走,与在线请求同一口径
    return {
        "custom_id": item["custom_id"],
        "method": "POST",
        "url": ENDPOINT,
        "body": {
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "max_tokens": cfg["max_tokens"],
        },
    }


def upload_file(line_path: Path) -> str:
    with line_path.open("rb") as f:
        r = _req(
            "POST",
            "/v1/files",
            data={"purpose": "batch"},
            files={"file": (line_path.name, f, "application/jsonl")},
        )
    fid = r.json().get("id")
    print(f"上传成功:{fid}")
    return fid


def cmd_submit(args) -> None:
    jobs = load_jobs()
    if args.retry:
        src = jobs.get(args.retry) or next(
            (j for b, j in jobs.items() if b.startswith(args.retry)), None
        )
        if src is None:
            raise SystemExit(f"没有这个任务:{args.retry}(现有:{', '.join(jobs) or '空'})")
        items = [dict(it) for it in (src.get("retry_items") or [])]  # 重掷不截断,全掷
        if not items:
            raise SystemExit(f"{src['batch_id']} 没有待重掷的词")
        for i, it in enumerate(items):
            it["custom_id"] = f"{it['mode']}-{i}"
        visited = list(load_cache().keys())
        mode_label = "+".join(sorted({it["mode"] for it in items}))
        scope_label = "retry"
        args.name = args.name or f"roam-retry-{src['batch_id'][-8:]}"
    else:
        modes = args.mode or ["detail"]
        items, visited = [], []
        for m in modes:  # 一个文件可以混模式(同端点),省一个队列位
            got, visited = pick_targets(m, args.scope, args.word or [], args.limit, args.flavor)
            items.extend(got)
        mode_label = "+".join(modes)
        scope_label = args.scope if args.scope == "related" else ("words" if args.word else args.scope)

    if not items:
        raise SystemExit("没有可提交的目标(缓存里该模式都齐了?)")
    if len(items) > MAX_REQUESTS:
        raise SystemExit(f"单批上限 {MAX_REQUESTS} 条(平台限制),当前 {len(items)} 条;先调小 --limit")

    IN_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    line_path = IN_DIR / f"{stamp}-{mode_label}-{scope_label}.jsonl"
    with line_path.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(build_line(it, visited), ensure_ascii=False) + "\n")
    size = line_path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise SystemExit(f"文件 {size / 1048576:.0f}MB 超过 128MB 上限,先调小 --limit")
    # 附一份映射清单:custom_id → 词/模式,回填时靠它对号(手动上传路径同样用它)
    line_path.with_suffix(".map.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"已生成 {len(items)} 条请求({size / 1024:.0f} KB)→ {line_path}")
    if args.dry_run:
        print("首行样例:", json.dumps(build_line(items[0], visited), ensure_ascii=False)[:300])
        print("--dry-run:只生成文件没上传,检查无误后去掉 --dry-run 重跑。")
        print("(也可以拿去平台「创建批量任务」页面手动上传,跑完用 ingest-file 回填)")
        return

    _need_base()
    window = _window(args)
    file_id = upload_file(line_path)
    name = args.name or f"roam-{mode_label}-{scope_label}-{stamp}"
    batch = _req(
        "POST",
        "/v1/batches",
        json={
            "input_file_id": file_id,
            "endpoint": ENDPOINT,
            "completion_window": window,
            "name": name,
        },
    ).json()
    bid = batch["id"]
    jobs[bid] = {
        "batch_id": bid,
        "file_id": file_id,
        "name": name,
        "endpoint": ENDPOINT,
        "completion_window": window,
        "status": batch.get("status"),
        "created_at": batch.get("created_at") or int(time.time()),
        "output_file_id": None,
        "error_file_id": None,
        "items": items,
        "retry_items": [],
        "retry_of": args.retry or None,
        "ingested": False,
        "line_path": str(line_path.relative_to(BASE_DIR)),
    }
    save_jobs(jobs)
    print(f"任务已创建:{bid}  状态:{batch.get('status')}")
    print(f"之后:python batch.py poll  →  python batch.py ingest {bid}")


def cmd_poll(args) -> None:
    _need_base()
    jobs = load_jobs()
    if not jobs:
        raise SystemExit("本地还没有任务记录,先 submit")
    while True:
        pending = 0
        for bid, job in jobs.items():
            if job.get("ingested") and not args.all:
                continue
            data = _req("GET", f"/v1/batches/{bid}", timeout=30).json()
            job.update({
                "status": data.get("status"),
                "output_file_id": data.get("output_file_id"),
                "error_file_id": data.get("error_file_id"),
                "request_counts": data.get("request_counts"),
            })
            rc = data.get("request_counts") or {}
            counts = f"{rc.get('completed', 0)}/{rc.get('total', 0)} 完成"
            if rc.get("failed"):
                counts += f",{rc['failed']} 失败"
            print(f"{bid}  {job['status']:<12} {counts}  {job.get('name', '')}")
            if job["status"] not in TERMINAL:
                pending += 1
            elif job["status"] == "completed" and not job.get("ingested"):
                print(f"    → 可回填:python batch.py ingest {bid}")
        save_jobs(jobs)
        if not args.watch or pending == 0:
            break
        time.sleep(args.watch)


def _extract(rec: dict, word: str) -> tuple:
    """从批量结果行抠出 (解析后的 JSON, 思维链)。兜底与留痕跟在线 chat() 同款:
    截断记一笔、正文为空去思维链里捞、捞不到算失败。"""
    body = (rec.get("response") or {}).get("body") or {}
    choice = (body.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    reasoning = (msg.get("reasoning_content") or "").strip()
    content = (msg.get("content") or "").strip()
    if choice.get("finish_reason") == "length":
        log_abnormal("max_tokens截断(批量)", word, f"正文尾部:{content[-60:]!r}")
    if not content:
        content = reasoning
        log_abnormal("正文为空,兜底用思维链(批量)", word, f"思维链{len(reasoning)}字")
    if not content:
        raise ValueError(f"批量返回为空(finish_reason={choice.get('finish_reason')})")
    return parse_llm_json(content), reasoning


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        raise SystemExit(f"文件不存在:{path}")
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _apply_output(records: list, by_id: dict, cache: dict) -> dict:
    """成功文件逐条:校验→并进缓存→计数。校验不过的收进 retry 队列(对应在线重掷一次)。
    API 路径(ingest)和页面手动上传路径(ingest-file)共用这一份。"""
    ok, bad, retry = 0, 0, []
    for rec in records:
        it = by_id.get(rec.get("custom_id"))
        if it is None:
            log_abnormal("批量结果对不上号", str(rec.get("custom_id"))[:40], "输入映射里没有这个 custom_id")
            bad += 1
            continue
        try:
            data_, reasoning = _extract(rec, it["word"])
            _validate(data_, it["mode"], it["word"], reasoning)
        except (ValueError, AssertionError, json.JSONDecodeError) as e:
            bad += 1
            log_abnormal("批量校验不过", it["word"], str(e)[:200])
            retry.append({
                "word": it["word"],
                "mode": it["mode"],
                "flavor": it.get("flavor") or DEFAULT_FLAVOR,
                "ctx": it.get("ctx", ""),
                "why": str(e)[:80],
            })
            continue
        if it["mode"] == "basic":
            data_["src"] = "batch"  # 标注来源是批量预热,前端暂不展示
        merge_into_cache(cache, it["word"], it["mode"], data_, it.get("flavor") or DEFAULT_FLAVOR)
        save_cache(cache)
        ok += 1
    return {"ok": ok, "bad": bad, "retry": retry}


def _apply_errors(records: list, by_id: dict) -> int:
    """错误文件逐条留痕,返回条数。"""
    for rec in records:
        it = by_id.get(rec.get("custom_id")) or {}
        err = rec.get("error") or {}
        log_abnormal("批量请求失败", it.get("word", "?"), f"{err.get('code', '')} {err.get('message', '')}"[:200])
    return len(records)


def _write_retry_file(items: list, path: Path) -> Path:
    """把重掷的词重拼成一份可直接上传的输入文件(词表/提示词与在线一致)。"""
    visited = list(load_cache().keys())
    for i, it in enumerate(items):
        it["custom_id"] = f"{it['mode']}-{i}"
    path.write_text(
        "\n".join(json.dumps(build_line(it, visited), ensure_ascii=False) for it in items) + "\n",
        encoding="utf-8",
    )
    return path


def cmd_ingest(args) -> None:
    jobs = load_jobs()
    job = jobs.get(args.batch_id) or next(
        (j for b, j in jobs.items() if b.startswith(args.batch_id)), None
    )
    if job is None:
        raise SystemExit(f"没找到任务 {args.batch_id}(现有:{', '.join(jobs) or '空'})")
    if job.get("ingested") and not args.force:
        raise SystemExit(f"{job['batch_id']} 已经回填过;确有需要加 --force 重来")
    _need_base()
    bid = job["batch_id"]

    data = _req("GET", f"/v1/batches/{bid}", timeout=30).json()
    job.update({
        "status": data.get("status"),
        "output_file_id": data.get("output_file_id"),
        "error_file_id": data.get("error_file_id"),
        "request_counts": data.get("request_counts"),
    })
    if job["status"] not in TERMINAL:
        raise SystemExit(f"{bid} 还在 {job['status']},等完成后再回填")

    by_id = {it["custom_id"]: it for it in job["items"]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    job["retry_items"] = []
    res = {"ok": 0, "bad": 0, "retry": []}
    fail = 0

    if job["output_file_id"]:
        out_path = OUT_DIR / f"{bid}.output.jsonl"
        out_path.write_bytes(
            _req("GET", f"/v1/files/{job['output_file_id']}/content", timeout=180).content
        )
        print(f"成功文件已存:{out_path}")
        res = _apply_output(_read_jsonl(out_path), by_id, cache)
        job["retry_items"] = res["retry"]

    if job["error_file_id"]:
        err_path = OUT_DIR / f"{bid}.errors.jsonl"
        err_path.write_bytes(
            _req("GET", f"/v1/files/{job['error_file_id']}/content", timeout=180).content
        )
        print(f"错误文件已存:{err_path}")
        fail = _apply_errors(_read_jsonl(err_path), by_id)

    job["ingested"] = True
    save_jobs(jobs)
    print(f"\n回填完成:成功 {res['ok']} / 校验不过 {res['bad']}(已记入重掷队列) / 接口失败 {fail}")
    if job["retry_items"]:
        print(f"重掷:{len(job['retry_items'])} 个词 → python batch.py submit --retry {bid}")


def cmd_ingest_file(args) -> None:
    """手动路径:平台页面下载的结果文件回填(不需要 Base URL/API Key)。
    靠 submit 生成的同名 .map.json 把 custom_id 对回词。"""
    in_path, out_path = Path(args.input), Path(args.output)
    map_path = in_path.with_suffix(".map.json")
    if not map_path.exists():
        raise SystemExit(f"缺映射文件 {map_path.name};它由 submit 生成,和输入文件同目录同名")
    by_id = {it["custom_id"]: it for it in json.loads(map_path.read_text(encoding="utf-8"))}

    cache = load_cache()
    res = _apply_output(_read_jsonl(out_path), by_id, cache)
    fail = _apply_errors(_read_jsonl(Path(args.errors)), by_id) if args.errors else 0

    print(f"\n回填完成:成功 {res['ok']} / 校验不过 {res['bad']} / 接口失败 {fail}")
    if res["retry"]:
        retry_path = _write_retry_file(res["retry"], in_path.with_suffix(".retry.jsonl"))
        print(f"重掷:{len(res['retry'])} 个词已拼成新输入文件 → {retry_path}")
        print("       再拿去平台页面传一次即可(这次不用再挑词,文件里就是那几个没过关的)")


def cmd_agent_prepare(args) -> None:
    """会话模型直生成·出题:挑词+完整提示词写成本地文件,由对话里的模型答卷。
    提示词仍走 build_prompt,和在线/批量同一套拼装,只是答卷人不换模型换人。"""
    items, visited = [], list(load_cache().keys())
    for m in (args.mode or ["detail"]):
        got, visited = pick_targets(m, args.scope, args.word or [], args.limit, args.flavor)
        items.extend(got)
    if not items:
        raise SystemExit("没有可生成的目标(该模式都齐了?换个 --scope 或用 --word 指定)")
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    modes_tag = "-".join(args.mode or ["detail"])
    todo = AGENT_DIR / f"todo-{stamp}-{modes_tag}.jsonl"
    n = 2
    while todo.exists():  # 同一秒出两份题时别互相覆盖
        todo = AGENT_DIR / f"todo-{stamp}-{modes_tag}-{n}.jsonl"
        n += 1
    with todo.open("w", encoding="utf-8") as f:
        for it in items:
            system, user_msg, temperature = build_prompt(
                it["word"], it["flavor"], visited, mode=it["mode"], ctx=it.get("ctx", "")
            )
            f.write(json.dumps({**it, "system": system, "user": user_msg}, ensure_ascii=False) + "\n")
    print(f"出题 {len(items)} 条 → {todo.relative_to(BASE_DIR)}")
    print("答卷人(对话里的模型)逐条按 system+user 生成正文,每行一条写进答卷文件:")
    print(f'  {{"custom_id": "{(items[0]["custom_id"])}", "content": "<按该条提示词生成的原文>"}}')
    print(f"然后收卷:python batch.py agent-merge {todo.name} <答卷文件路径>")


def _agent_file(name: str) -> Path:
    """出题文件:写全路径就用,只给文件名就到 data/agent_in/ 下找。"""
    p = Path(name)
    return p if p.exists() else AGENT_DIR / name


def cmd_agent_merge(args) -> None:
    """会话模型直生成·收卷:答卷逐条 parse→校验→并进缓存,不过的点名让答卷人重写。
    与 _apply_output 同一套校验/合并,差别只在答卷格式(content 字段)和来源标记。"""
    by_id = {rec["custom_id"]: rec for rec in _read_jsonl(_agent_file(args.todo))}
    cache = load_cache()
    ok = bad = 0
    failed = []
    for rec in _read_jsonl(_agent_file(args.answers)):
        it = by_id.get(rec.get("custom_id"))
        if it is None:
            log_abnormal("Agent答卷对不上号", str(rec.get("custom_id"))[:40], "出题文件里没有这个 custom_id")
            bad += 1
            continue
        try:
            data_ = parse_llm_json((rec.get("content") or "").strip())
            _validate(data_, it["mode"], it["word"], (rec.get("reasoning") or "").strip())
        except (ValueError, AssertionError, json.JSONDecodeError) as e:
            bad += 1
            log_abnormal("Agent答卷校验不过", it["word"], str(e)[:200])
            failed.append(f"{it['word']}({it['mode']}):{str(e)[:60]}")
            continue
        if it["mode"] == "basic":
            data_["src"] = "agent"  # 标注来源是会话模型,前端暂不展示
        merge_into_cache(cache, it["word"], it["mode"], data_, it.get("flavor") or DEFAULT_FLAVOR)
        save_cache(cache)
        ok += 1
    print(f"收卷完成:成功 {ok} / 不过 {bad}")
    if failed:
        print("没过关的,重写 content 再收一轮:")
        for f_ in failed:
            print(f"  {f_}")


def prewarm_one(item: dict, visited: list) -> tuple:
    """在线跑一个目标:call_llm 自带两层重掷(网络/JSON/校验),外面再加退避防限流。"""
    last: Exception = ValueError("未执行")
    for attempt in range(3):
        try:
            return call_llm(item["word"], item["flavor"], visited, mode=item["mode"], ctx=item.get("ctx", "")), None
        except Exception as e:  # 网络抖动/429/偶发坏 JSON 都退避再来,call_llm 内部已留痕
            last = e
            if attempt + 1 < 3:
                time.sleep(2 ** attempt + random.random())
    return None, last


def _run_prewarm_batch(items: list, visited: list, concurrency: int) -> tuple:
    """并发跑一批在线生成,边成功边并进缓存。返回 (成功数, 总数)。"""
    cache = load_cache()
    lock = threading.Lock()   # 合并+落盘串行,请求本身并发
    t0, done, ok = time.time(), 0, 0
    print(f"在线预热 {len(items)} 条,并发 {concurrency}(平台限流 RPM=100/TPM=10M,429 自动退避)…")

    def work(it):
        data, err = prewarm_one(it, visited)
        return it, data, err

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        for fut in as_completed([ex.submit(work, it) for it in items]):
            it, data, err = fut.result()
            with lock:
                done += 1
                if data is not None:
                    if it["mode"] == "basic":
                        data["src"] = "prewarm"  # 标来源是机器铺图,前端暂不展示
                    merge_into_cache(cache, it["word"], it["mode"], data, it.get("flavor") or DEFAULT_FLAVOR)
                    save_cache(cache)
                    ok += 1
                    print(f"  ✓ {done}/{len(items)} [{it['mode']}] {it['word']}")
                else:
                    log_abnormal("预热失败(重试耗尽)", it["word"], str(err)[:200])
                    print(f"  ✗ {done}/{len(items)} [{it['mode']}] {it['word']}:{str(err)[:80]}")

    rate = done / max((time.time() - t0) / 60, 1e-9)
    print(f"  本批完成:成功 {ok}/{len(items)},速率约 {rate:.0f} 条/分钟")
    return ok, len(items)


def cmd_prewarm(args) -> None:
    """在线并发预热:与在线请求同一出口(app.call_llm),线程池并发,合并进缓存。"""
    _miss = missing_hint(resolve_api_config())
    if _miss:
        raise SystemExit(f"{_miss}(在线预热要用)")
    modes = args.mode or ["detail"]
    items, visited = [], []
    for m in modes:
        got, visited = pick_targets(m, args.scope, args.word or [], args.limit, args.flavor)
        items.extend(got)
    if not items:
        raise SystemExit("没有可预热的目标(缓存里该模式都齐了?)")
    if args.dry_run:
        print(f"将在线并发生成 {len(items)} 条(并发 {args.concurrency}):")
        for it in items[:10]:
            print(f"  [{it['mode']}] {it['word']}" + (f"  ← {it['ctx']}" if it.get("ctx") else ""))
        if len(items) > 10:
            print(f"  …共 {len(items)} 条")
        return

    ok, total = _run_prewarm_batch(items, visited, args.concurrency)

    print(f"\n预热完成:成功 {ok}/{total},已并入缓存")
    if ok < total:
        print(f"失败 {total - ok} 条已留痕 abnormal.log;重跑同一句即可——按 scope 挑词只挑还缺的,已成功的不会重跑")


def cmd_jobs(_args) -> None:
    jobs = load_jobs()
    if not jobs:
        print("(还没有任务记录)")
        return
    for bid, job in jobs.items():
        rc = job.get("request_counts") or {}
        state = "已回填" if job.get("ingested") else ("可回填" if job.get("status") == "completed" else "")
        retry = f"  待重掷{len(job.get('retry_items') or [])}" if job.get("retry_items") else ""
        print(f"{bid}  {job.get('status', '?'):<12} {rc.get('completed', 0)}/{rc.get('total', 0)}  {job.get('name', '')}  {state}{retry}")


def main() -> None:
    ap = argparse.ArgumentParser(description="缓存预热:在线并发(快)或离线批量(省),给 data/cache.json 铺图")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prewarm", help="在线并发预热:直接打现有端点,RPM 限流内并发(快,全价)")
    p.add_argument("--mode", action="append", choices=("basic", "deep", "detail"),
                   help="生成哪种数据;可重复,默认 detail")
    p.add_argument("--scope", choices=("missing", "neighbors", "related"), default="missing",
                   help="missing=缓存里缺该模式的词;neighbors=漫游图里没走过的词;"
                        "related=--word 那几棵树里的每个词(配 --mode detail 用)")
    p.add_argument("--word", action="append", help="指定词(可重复);给了就不看 scope")
    p.add_argument("--limit", type=int, default=100, help="每个模式最多多少条,默认 100")
    p.add_argument("--flavor", default="", help="口味偏好;缺省用缓存里该词的,再缺省用默认口味")
    p.add_argument("--concurrency", type=int, default=8, help="并发线程数,默认 8(RPM=100,超了会 429,已带退避)")
    p.add_argument("--dry-run", action="store_true", help="只列出要生成什么,不发请求")
    p.set_defaults(func=cmd_prewarm)

    p = sub.add_parser("submit", help="挑目标→生成 JSONL→上传→建任务(离线批量)")
    p.add_argument("--mode", action="append", choices=("basic", "deep", "detail"),
                   help="生成哪种数据;可重复(--mode basic --mode deep 混进一个文件,少排一个队),默认 detail")
    p.add_argument("--scope", choices=("missing", "neighbors", "related"), default="missing",
                   help="missing=缓存里缺该模式的词;neighbors=漫游图里没走过的词;"
                        "related=--word 那几棵树里的每个词(配 --mode detail 用)")
    p.add_argument("--word", action="append", help="指定词(可重复);给了就不看 scope")
    p.add_argument("--limit", type=int, default=100, help="每个模式最多提交多少条,默认 100")
    p.add_argument("--flavor", default="", help="口味偏好;缺省用缓存里该词的,再缺省用默认口味")
    p.add_argument("--window", default="", help="最长等待时间,原样透传(如 24h);不填则用 --days")
    p.add_argument("--days", type=int, default=0, help="最长等待时间按天填(1~14,对齐控制台;默认 7 天)")
    p.add_argument("--name", default="", help="任务名")
    p.add_argument("--dry-run", action="store_true", help="只生成 jsonl,不上传")
    p.add_argument("--retry", default="", help="用某任务的 retry_items 再掷一轮")
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser("poll", help="查任务进度")
    p.add_argument("--watch", type=int, default=0, metavar="秒", help="每 N 秒循环盯,直到都到终态")
    p.add_argument("--all", action="store_true", help="连已回填的任务也查")
    p.set_defaults(func=cmd_poll)

    p = sub.add_parser("ingest", help="下结果→校验→并进 cache.json")
    p.add_argument("batch_id")
    p.add_argument("--force", action="store_true", help="已回填过也重来")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("ingest-file", help="手动路径:用平台页面下载的结果文件回填(不用 Base URL/Key)")
    p.add_argument("input", help="当初上传的输入 jsonl(同目录需有同名 .map.json)")
    p.add_argument("output", help="页面下载的成功结果文件")
    p.add_argument("--errors", default="", help="页面下载的错误文件(可选)")
    p.set_defaults(func=cmd_ingest_file)

    p = sub.add_parser("agent-prepare", help="会话模型直生成·出题:挑词+提示词写成文件(零 API 费)")
    p.add_argument("--mode", action="append", choices=("basic", "deep", "detail"),
                   help="生成哪种数据;可重复,默认 detail")
    p.add_argument("--scope", choices=("missing", "neighbors", "related"), default="missing",
                   help="missing=缓存里缺该模式的词;neighbors=漫游图里没走过的词;"
                        "related=--word 那几棵树里的每个词(配 --mode detail 用)")
    p.add_argument("--word", action="append", help="指定词(可重复);给了就不看 scope")
    p.add_argument("--limit", type=int, default=100, help="每个模式最多多少条,默认 100")
    p.add_argument("--flavor", default="", help="口味偏好;缺省用缓存里该词的,再缺省用默认口味")
    p.set_defaults(func=cmd_agent_prepare)

    p = sub.add_parser("agent-merge", help="会话模型直生成·收卷:答卷校验→并进 cache.json")
    p.add_argument("todo", help="agent-prepare 生成的出题文件名(在 data/agent_in/ 下)")
    p.add_argument("answers", help="答卷 jsonl,每行 {custom_id, content}")
    p.set_defaults(func=cmd_agent_merge)

    sub.add_parser("jobs", help="看本地任务记录").set_defaults(func=cmd_jobs)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()