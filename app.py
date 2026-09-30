"""关键词漫游器:给一个词,返回上级分类/下级分类/相邻词,人挑有意思的去 B 站搜视频。

用法:
    setx DEEPSEEK_API_KEY "sk-..."   # 或在 PowerShell 里 $env:DEEPSEEK_API_KEY="sk-..."
    python app.py                    # 打开 http://127.0.0.1:8765

数据:
    data/cache.json 保存漫游过的关键词图,查过的词不再请求 API(省钱 + 地图越滚越大)。
"""
import json
import os
import time
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "data" / "cache.json"
ASKS_FILE = BASE_DIR / "data" / "asks.json"

# 万能插座:任何 OpenAI 兼容端点都能接(Ollama 填 http://localhost:11434/v1 即可)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
API_URL = LLM_BASE_URL + "/chat/completions"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")  # 漫游要快和便宜,flash 够用;要更聪明改 deepseek-v4-pro
MAX_TOKENS = int(os.environ.get("ROAM_MAX_TOKENS", "8000"))  # 思维链+正文共用,大词(如微软)思考就得上千 token

DEFAULT_FLAVOR = "半学习半娱乐,科技/商业/历史/人文乱炖,别太正经"

SYSTEM_PROMPT = """你是一个关键词漫游引擎,帮用户从一个词出发发现有意思的邻近词,用于去视频网站找内容看。
用户给你一个关键词,你从三个方向扩展:
- parents(上级):这个词属于什么更大的领域或类别,2~3 个
- children(下级):这个词的子话题、子类或具体例子,4~8 个
- similar(相邻):气质相似、经常一起出现、顺着看很自然的词,8~12 个,其中至少 2 个要跳出本领域制造惊喜

要求:
1. 每个词配一句"勾人说明",不超过 15 个字,说清为什么值得搜来看
2. 避免输出用户已访问过的词(会在用户消息里给出)
3. 优先输出具体、有画面感的词,不要输出空泛的大词
4. 所有词必须是真实存在、能在 B 站/百科搜到实质内容的词或短语;禁止生造词、禁止把两个词临时拼接成新词
5. 只输出 JSON,格式:
{"word":"中心词","parents":[{"word":"...","note":"..."}],"children":[{"word":"...","note":"..."}],"similar":[{"word":"...","note":"..."}]}"""

DEEP_SYSTEM_PROMPT = """你是关键词深挖引擎。用户给你一个词,先判断它的类型(事件/人物/概念/技术/作品/地点/组织等),再按类型选择 4~6 个最值得深挖的维度。

不同类型的维度参考(按词的实际情况灵活选择):
- 事件:起因、关键人物、时间线、地点、后果与影响、相关事件
- 人物:身份与领域、代表事迹或作品、同时代相关人物、师承与影响、争议点
- 概念/技术:定义与起源、关键人物、代表实现或案例、相邻概念、常见误解、争议
- 地点:相关历史事件、文化符号、代表性事物、相关作品
- 组织:历史沿革、关键人物、代表产品、相关组织、争议点

要求:
1. 每个维度给 3~6 个词条目,每词配一句"勾人说明",不超过 15 字
2. 词必须真实存在、能在 B 站/百科搜到实质内容;禁止生造词、禁止拼接新词
3. 避免输出用户已访问过的词(会在用户消息里给出)
4. 优先输出具体、有画面感的词
5. 只输出 JSON,格式:
{"type":"词的类型","summary":"一句话定位这个词,20字内","dimensions":[{"name":"维度名","items":[{"word":"...","note":"..."}]}]}"""

DETAIL_SYSTEM_PROMPT = """你是词条解释器。用户给的输入可能是一个词、一个短语,也可能是一句描述或说法(例如"某某 2014 年上线,2023 年关闭")。
- 输入是词或短语:直接解释它是什么、为什么有意思,可带一两个关键事实(时间/人物/数字)
- 输入是描述或说法:先推断它实际指的是什么(把推断出的名称写进 word 字段),再解释那个东西
要求:
1. 解释不超过 150 个汉字,宁可砍细节
2. 面向好奇但没背景的普通人,信息密度高,不要营销腔,不要堆感叹号
3. 只输出 JSON:{"word":"...","detail":"150字以内的解释"}"""

ASK_SYSTEM_PROMPT = """你是追问助手。用户正在阅读关于某个关键词的介绍,对里面不熟悉的说法产生了疑问。
基于给出的上下文回答用户的问题,要求:
1. 不超过 150 个汉字,直接回答问题本身,信息密度高,面向没背景的普通人
2. 上下文没有的信息也可以答,但不确定就诚实说不确定,别编
3. 只输出 JSON:{"answer":"150字以内的回答"}"""

app = Flask(__name__)


def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def load_asks() -> dict:
    if ASKS_FILE.exists():
        return json.loads(ASKS_FILE.read_text(encoding="utf-8"))
    return {}


def save_asks(asks: dict) -> None:
    ASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ASKS_FILE.write_text(
        json.dumps(asks, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def parse_llm_json(text: str) -> dict:
    """从模型返回文本里抠 JSON:容忍 ```json 围栏和思考残留的前后废话。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise json.JSONDecodeError("没找到 JSON", text, 0)


def chat(system: str, user_msg: str, temperature: float = 1.1, retries: int = 2) -> tuple:
    """发一次对话请求,返回 (解析后的 JSON, 思维链思考过程)。
    网络抖动或模型偶发写崩 JSON 时自动重试一次——温度高就是掷骰子,重掷一次通常就好。"""
    last_err: Exception = ValueError("未执行")
    for attempt in range(retries):
        try:
            resp = requests.post(
                API_URL,
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_msg},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": temperature,
                    "max_tokens": MAX_TOKENS,  # 思维链+正文共用;按实际用量计费,上限抬高不多花钱
                },
                timeout=90,
            )
            resp.raise_for_status()
            choice = resp.json()["choices"][0]
            msg = choice["message"]

            reasoning = (msg.get("reasoning_content") or "").strip()  # 深度思考过程,单独留存
            content = (msg.get("content") or "").strip()
            if not content:
                # flash 是思维链模型:思考在 reasoning_content 里,正文可能为空,兜底去思考内容里捞
                content = reasoning
            if not content:
                raise ValueError(f"模型返回为空(finish_reason={choice.get('finish_reason')})")
            return parse_llm_json(content), reasoning
        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            last_err = e
            if attempt + 1 < retries:
                time.sleep(1)  # 缓一秒再掷骰子
    raise last_err


def call_llm(word: str, flavor: str, visited: list[str], mode: str = "basic") -> dict:
    """调 DeepSeek 生成扩展词。mode=basic 普通漫游,mode=deep 按类型深挖。"""
    visited_text = "、".join(visited[-40:]) if visited else "(还没有)"
    user_msg = f"关键词:{word}\n口味偏好:{flavor}\n已访问过(不要重复推荐):{visited_text}"
    system = {"basic": SYSTEM_PROMPT, "deep": DEEP_SYSTEM_PROMPT, "detail": DETAIL_SYSTEM_PROMPT}[mode]
    temperature = 0.7 if mode == "detail" else 1.1  # 详情/追问求准,漫游求惊喜

    data, reasoning = chat(system, user_msg, temperature=temperature)

    # 最小校验,防止模型抽风污染缓存
    if mode == "basic":
        for key in ("parents", "children", "similar"):
            assert isinstance(data.get(key), list), f"模型返回缺少 {key}"
    elif mode == "deep":
        assert isinstance(data.get("dimensions"), list) and data["dimensions"], "模型返回缺少 dimensions"
        data["thinking"] = reasoning  # 深挖把思维链一起存下来,前端可单独查看
    else:  # detail
        assert isinstance(data.get("detail"), str) and data["detail"].strip(), "模型返回缺少 detail"
        assert len(data["detail"]) <= 300, f"解释超长({len(data['detail'])}字)"
    return data


@app.route("/")
def index():
    return render_template("index.html", default_flavor=DEFAULT_FLAVOR)


@app.route("/api/expand")
def expand():
    if not API_KEY and "deepseek.com" in API_URL:
        # 自建/本地端点通常不需要 key,只在走 DeepSeek 官方时强制
        return jsonify({"error": "未设置 DEEPSEEK_API_KEY 环境变量,设置后重启本程序"}), 500

    word = request.args.get("word", "").strip()
    if not word:
        return jsonify({"error": "缺少 word 参数"}), 400
    if len(word) > 30:
        return jsonify({"error": "词太长了"}), 400

    flavor = request.args.get("flavor", "").strip() or DEFAULT_FLAVOR
    mode = request.args.get("mode", "basic")
    if mode not in ("basic", "deep", "detail"):
        return jsonify({"error": "mode 只能是 basic / deep / detail"}), 400

    cache = load_cache()
    entry = cache.get(word)

    # 缓存命中:漫游看词条本身,深挖和详情看词条里嵌的对应字段
    if entry is not None:
        if mode == "basic" and entry.get("parents"):
            return jsonify({"cached": True, "data": entry})
        if mode == "deep" and entry.get("deep"):
            return jsonify({"cached": True, "data": entry["deep"]})
        if mode == "detail" and entry.get("detail"):
            return jsonify({"cached": True, "data": {"word": word, "detail": entry["detail"]}})

    try:
        data = call_llm(word, flavor, list(cache.keys()), mode=mode)
    except requests.RequestException as e:
        return jsonify({"error": f"API 请求失败:{e}"}), 502
    except (json.JSONDecodeError, AssertionError, ValueError) as e:
        return jsonify({"error": f"模型返回解析失败:{e}"}), 502

    if mode == "basic":
        data["word"] = word
        data["flavor"] = flavor
        data["time"] = int(time.time())
        if entry is not None and entry.get("deep"):
            data["deep"] = entry["deep"]  # 别把已存的深挖结果冲掉
        if entry is not None and entry.get("detail"):
            data["detail"] = entry["detail"]  # 详情同理
        cache[word] = data
    else:
        # 深挖/详情嵌在词条字段里,不污染足迹词表
        entry = cache.get(word) or {"word": word, "time": int(time.time())}
        data["word"] = word
        if mode == "deep":
            entry["deep"] = data
        else:
            entry["detail"] = data["detail"]

        cache[word] = entry

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

    if not API_KEY and "deepseek.com" in API_URL:
        return jsonify({"error": "未设置 DEEPSEEK_API_KEY 环境变量,设置后重启本程序"}), 500

    user_msg = f"中心词:{word or '(无)'}\n正在阅读的介绍:{context or '(无)'}\n我的问题:{question}"
    try:
        data, _reasoning = chat(ASK_SYSTEM_PROMPT, user_msg, temperature=0.7)  # 追问求准,温度降回来
        assert isinstance(data.get("answer"), str) and data["answer"].strip(), "模型返回缺少 answer"
    except requests.RequestException as e:
        return jsonify({"error": f"API 请求失败:{e}"}), 502
    except (json.JSONDecodeError, AssertionError, ValueError) as e:
        return jsonify({"error": f"回答生成失败:{e}"}), 502

    entry = {"word": word, "question": question, "answer": data["answer"], "time": int(time.time())}
    asks[key] = entry
    save_asks(asks)
    return jsonify({"cached": False, "data": entry})


@app.route("/api/cache")
def cache_info():
    """给前端:已漫游过的词,按最近漫游排序(前端加载历史足迹用)。"""
    cache = load_cache()
    words = sorted(
        ({"word": w, "time": d.get("time") or 0} for w, d in cache.items()),
        key=lambda x: x["time"],
        reverse=True,
    )
    return jsonify({"count": len(words), "words": [x["word"] for x in words]})


if __name__ == "__main__":
    port = int(os.environ.get("ROAM_PORT", "8765"))
    print(f"关键词漫游器:http://127.0.0.1:{port}   (模型:{MODEL})")
    app.run(host="127.0.0.1", port=port, debug=False)
