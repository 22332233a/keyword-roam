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
DEFAULT_SETTINGS = {"detail_len": "标准", "temp_style": "标准", "flavors": [], "blacklist": []}
DETAIL_LEN_CHARS = {"短": 80, "标准": 150, "长": 300}    # 详情提示词的目标字数
DETAIL_CAP_CHARS = {"短": 160, "标准": 300, "长": 460}   # 校验硬上限,给发挥留余量
TEMP_ROAM = {"稳": 0.8, "标准": 1.1, "抽风": 1.5}        # 漫游求惊喜,幅度大
TEMP_DETAIL = {"稳": 0.5, "标准": 0.7, "抽风": 1.0}      # 详情求准,整体压低


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
    if not isinstance(s["flavors"], list):
        s["flavors"] = []
    s["flavors"] = [str(f).strip()[:60] for f in s["flavors"] if str(f).strip()][:20]
    if not isinstance(s["blacklist"], list):
        s["blacklist"] = []
    s["blacklist"] = [str(w).strip()[:30] for w in s["blacklist"] if str(w).strip()][:200]
    return s


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
        cache[word] = data
    else:
        entry = cache.get(word) or {"word": word, "time": int(time.time())}
        data["word"] = word
        if mode == "deep":
            entry["deep"] = data
        else:
            entry["detail"] = data["detail"]
        cache[word] = entry
