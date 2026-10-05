"""数据层:关键词漫游器的所有文件读写。

cache(足迹图)/asks(追问缓存)/notes(手写笔记)/settings(用户偏好)四份 JSON,
外加 abnormal.log 异常留痕。在线路由和 batch.py 共用这一份,不许各写各的。

通用工具 load_json/save_json 是所有 load_xxx/save_xxx 的公共底座:
    load_json(path, default)  文件不存在/解析失败 → 落回 default(数据坏了不该连累功能)
    save_json(path, data)     原子性一般(整文件覆写),调用方自行保证不并发写同一文件
"""
import json
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "data" / "cache.json"
ASKS_FILE = BASE_DIR / "data" / "asks.json"
NOTES_FILE = BASE_DIR / "data" / "notes.json"
SETTINGS_FILE = BASE_DIR / "data" / "settings.json"
LOG_FILE = BASE_DIR / "data" / "abnormal.log"


def load_json(path: Path, default):
    """JSON 文件读取的公共底座:不存在/解析失败 → 落回 default。"""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_json(path: Path, data) -> None:
    """JSON 文件写入的公共底座:整文件覆写,父目录不存在自动创建。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load_cache() -> dict:
    return load_json(CACHE_FILE, {})


def save_cache(cache: dict) -> None:
    save_json(CACHE_FILE, cache)


def load_asks() -> dict:
    return load_json(ASKS_FILE, {})


def save_asks(asks: dict) -> None:
    save_json(ASKS_FILE, asks)


def load_notes() -> dict:
    return load_json(NOTES_FILE, {})


def save_notes(notes: dict) -> None:
    save_json(NOTES_FILE, notes)


_LOG_LOCK = threading.Lock()   # Flask 开发服务器默认多线程,在线并发预热也会多线程写,行不能串


def log_abnormal(kind: str, who: str, detail: str = "") -> None:
    """异常数据留痕(腰斩的句子/空返回/绕路解析…),写 data/abnormal.log 供事后翻账。"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with _LOG_LOCK:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {kind} | {who} | {detail}\n")


# ===== ⚙ 用户设置(data/settings.json,单机个人化):详情长度/放飞程度/口味预设 =====
# api 组:模型接口配置。空字符串 = 没配 → llm.py 回落到环境变量(兼容 setx 的老用法)
DEFAULT_SETTINGS = {
    "detail_len": "标准",
    "temp_style": "标准",
    "flavors": [],
    "blacklist": [],
    "auto_detail": "smart",   # 漫游后自动补详情:off 关 / smart 只补下级+相邻 / all 连上级也补
    "api": {"base_url": "", "key": "", "model": "", "temperature": "", "max_tokens": ""},
}
AUTO_DETAIL_MODES = ("off", "smart", "all")
DETAIL_LEN_CHARS = {"短": 80, "标准": 150, "长": 300}    # 详情提示词的目标字数
DETAIL_CAP_CHARS = {"短": 160, "标准": 300, "长": 460}   # 校验硬上限,给发挥留余量
TEMP_ROAM = {"稳": 0.8, "标准": 1.1, "抽风": 1.5}        # 漫游求惊喜,幅度大
TEMP_DETAIL = {"稳": 0.5, "标准": 0.7, "抽风": 1.0}      # 详情求准,整体压低

KEY_CLEAR = "__CLEAR__"   # 前端显式清除 key 的哨兵值(空字符串表示"别动")

# 详情生成失败几次后不再自动重试(手动点/重掷仍会打)。
# 起因是一个真实的循环:某个词死活生成不出合格详情(腰斩),自动补详情每次都会
# 重新把它排进队列——每漫游一次、每次刷新后重进都白花一次钱,而且永远好不了。
DETAIL_FAIL_LIMIT = 3


def _norm_api(raw) -> dict:
    """把 api 组洗成合法值。非法/缺失一律回落空字符串(=去读环境变量),不抛错。"""
    a = dict(DEFAULT_SETTINGS["api"])
    if isinstance(raw, dict):
        a.update({k: raw[k] for k in a if k in raw})
    for k in ("base_url", "key", "model", "temperature", "max_tokens"):
        a[k] = str(a.get(k) or "").strip()
    a["base_url"] = a["base_url"][:300]
    a["key"] = a["key"][:300]
    a["model"] = a["model"][:100]
    # 数值字段只留合法数值,否则清空
    for k in ("temperature", "max_tokens"):
        if a[k]:
            try:
                v = float(a[k])
                if k == "max_tokens":
                    v = int(v)
                    if not 1 <= v <= 200000:
                        raise ValueError
                    a[k] = str(v)
                else:
                    if not 0.0 <= v <= 2.0:
                        raise ValueError
                    a[k] = str(v)
            except (TypeError, ValueError):
                a[k] = ""
    return a


def load_settings() -> dict:
    """读用户设置;缺失/损坏/非法值一律落回默认——设置坏了不该连累漫游。"""
    s = dict(DEFAULT_SETTINGS)
    saved = load_json(SETTINGS_FILE, None)
    if isinstance(saved, dict):
        s.update({k: saved[k] for k in DEFAULT_SETTINGS if k in saved})
    if s["detail_len"] not in DETAIL_LEN_CHARS:
        s["detail_len"] = "标准"
    if s["temp_style"] not in TEMP_ROAM:
        s["temp_style"] = "标准"
    if s["auto_detail"] not in AUTO_DETAIL_MODES:
        s["auto_detail"] = "smart"
    if not isinstance(s["flavors"], list):
        s["flavors"] = []
    s["flavors"] = [str(f).strip()[:60] for f in s["flavors"] if str(f).strip()][:20]
    if not isinstance(s["blacklist"], list):
        s["blacklist"] = []
    s["blacklist"] = [str(w).strip()[:30] for w in s["blacklist"] if str(w).strip()][:200]
    s["api"] = _norm_api(s.get("api"))
    return s


def merge_api_settings(current: dict, incoming) -> dict:
    """合并 api 组更新。key 单独规则:空串=别动(前端拿不到原值,不能回传)、
    KEY_CLEAR=清除、其他=写入。"""
    cur = dict(current or DEFAULT_SETTINGS["api"])
    if not isinstance(incoming, dict):
        return cur
    for f in ("base_url", "model", "temperature", "max_tokens"):
        if f in incoming:
            cur[f] = incoming[f]
    if "key" in incoming:
        raw = str(incoming["key"] or "").strip()
        if raw == KEY_CLEAR:
            cur["key"] = ""
        elif raw:
            cur["key"] = raw
        # raw == "" → 保持原值(前端从不回传 key)
    return _norm_api(cur)


def mask_secret(v: str) -> str:
    """密钥预览:只露头尾各 4 位。"""
    v = v or ""
    if len(v) <= 12:
        return "…" if v else ""
    return f"{v[:4]}…{v[-4:]}"


def api_snapshot(s: dict) -> dict:
    """给前端的 api 视图:只回 key 的存在性+掩码预览,永不回原文。"""
    a = dict(s.get("api") or {})
    has_key = bool(a.get("key"))
    if has_key:
        a["key_preview"] = mask_secret(a["key"])
    else:
        a["key_preview"] = ""
    a["has_key"] = has_key
    a.pop("key", None)          # ← 原文绝不出后端
    return a


def save_settings(s: dict) -> None:
    save_json(SETTINGS_FILE, s)


def merge_into_cache(cache: dict, word: str, mode: str, data: dict, flavor: str = "") -> None:
    """把一次生成结果并进缓存条目:basic 整条写入,深挖/详情嵌进字段,不污染足迹词表。
    在线路由和批量回填共用,保证两条路的合并语义一致——回填不许冲掉已存的 deep/detail。"""
    if mode == "basic":
        data["word"] = word
        data["flavor"] = flavor
        data["time"] = int(time.time())
        entry = cache.get(word)
        if entry is not None and entry.get("deep"):
            data["deep"] = entry["deep"]  # 别把已存的深挖结果冲掉
        if entry is not None and entry.get("detail"):
            data["detail"] = entry["detail"]  # 详情同理
        if entry is not None and entry.get("failed"):
            data["failed"] = entry["failed"]  # 失败记录也留着,否则重掷一次漫游就把退避清零了
        cache[word] = data
    else:
        entry = cache.get(word) or {"word": word, "time": int(time.time())}
        data["word"] = word
        if mode == "deep":
            entry["deep"] = data
        elif mode == "detail":
            entry["detail"] = data["detail"]
            entry.pop("failed", None)   # 生成出来了 → 之前的失败记录作废
        else:
            entry[mode] = data
        cache[word] = entry


def detail_fail_count(entry: dict | None) -> int:
    """详情连续失败次数(0 = 没失败过或已作废)。
    failed 字段可能是任何东西(手改过的缓存/旧版本写坏了),一律当 0,不许抛异常。"""
    f = (entry or {}).get("failed")
    if not isinstance(f, dict):
        return 0
    try:
        return int(f.get("detail") or 0)
    except (TypeError, ValueError):
        return 0


def record_detail_fail(cache: dict, word: str) -> int:
    """记一次详情生成失败,返回累计次数。只对"已有条目"记账——不为失败凭空造足迹词条。"""
    entry = cache.get(word)
    if entry is None:
        return 0
    f = entry.get("failed")
    if not isinstance(f, dict):
        f = {}
    f["detail"] = detail_fail_count(entry) + 1
    f["time"] = int(time.time())
    entry["failed"] = f
    return f["detail"]


def clear_detail_fail(cache: dict, word: str) -> bool:
    """详情已经生成出来了 → 把失败记录清掉(旧记录留着会越攒越多,且会误判)。
    返回是否真的清掉了东西,调用方据此决定要不要落盘。"""
    entry = cache.get(word)
    if isinstance(entry, dict) and "failed" in entry:
        entry.pop("failed", None)
        return True
    return False


