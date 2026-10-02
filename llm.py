"""LLM 层:提示词模板、对话请求、结果解析与校验、请求拼装。

在线路由(/api/expand 等)和 batch.py 共用这一层:
    build_prompt → chat → parse_llm_json → _validate 的流水线两边一字不差。
    重掷策略:chat 里网络/解析重试 2 次(换骰子),call_llm 里校验不过再重掷 2 次(换答案)。
"""
import json
import os
import time

import requests

from store import (
    DETAIL_CAP_CHARS,
    DETAIL_LEN_CHARS,
    TEMP_DETAIL,
    TEMP_ROAM,
    load_settings,
    log_abnormal,
)

# 万能插座:任何 OpenAI 兼容端点都能接(Ollama 填 http://localhost:11434/v1 即可)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
API_URL = LLM_BASE_URL + "/chat/completions"
# key/模型名:通用名 LLM_* 优先,没设则回退到旧名 DEEPSEEK_*(兼容存量配置)
API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL") or os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")  # 漫游要快和便宜,flash 够用
MAX_TOKENS = int(os.environ.get("ROAM_MAX_TOKENS", "8000"))  # 思维链+正文共用,大词(如微软)思考就得上千 token

DEFAULT_FLAVOR = "半学习半娱乐,科技/商业/历史/人文乱炖,别太正经"

END_PUNCT = tuple("。！？…～」』）)】!?\"'")   # 正文/详情正常收尾的标点

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

CHAT_SYSTEM_PROMPT = """你是阅读陪聊助手。用户正在读关于某个关键词的介绍,在对话条里跟你连续追问。
基于关键词、介绍原文和之前的对话回答最新问题,要求:
1. 不超过 300 个汉字,信息密度高,面向没背景的普通人,别行话套行话
2. 对话里聊过的内容直接接着说,别当新问题重新开场
3. 上下文没有的信息也可以答,不确定就诚实说不确定,别编
4. 只输出 JSON:{"answer":"300字以内的回答"}"""


def parse_llm_json(text: str) -> dict:
    """从模型返回文本里抠 JSON:容忍 ```json 围栏和思考残留的前后废话。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        if start > 0 or end < len(text) - 1:
            # 没直接解析过、靠掐头去尾捞回来的,记一笔(模型前面夹了废话/思考残留)
            log_abnormal("JSON绕路解析", f"文本{len(text)}字", f"头部:{text[:60]!r}")
        return json.loads(text[start : end + 1])
    raise json.JSONDecodeError("没找到 JSON", text, 0)


def chat(system: str, user_msg: str, temperature: float = 1.1, retries: int = 2,
         extra_msgs: list | None = None) -> tuple:
    """发一次对话请求,返回 (解析后的 JSON, 思维链思考过程)。
    extra_msgs:多轮对话的中间消息(user/assistant 交替,最后一条应是 assistant),插在系统提示与本次提问之间。
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
                        *(extra_msgs or []),
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
            who = user_msg.splitlines()[0][:40]   # 拿消息头当身份(一般是"关键词:xxx")
            if choice.get("finish_reason") == "length":
                # token 预算用尽被硬切,正文多半话说到一半——正是"话说一半"的病根
                log_abnormal("max_tokens截断", who, f"正文尾部:{content[-60:]!r}")
            if not content:
                # flash 是思维链模型:思考在 reasoning_content 里,正文可能为空,兜底去思考内容里捞
                content = reasoning
                log_abnormal("正文为空,兜底用思维链", who, f"思维链{len(reasoning)}字")
            if not content:
                raise ValueError(f"模型返回为空(finish_reason={choice.get('finish_reason')})")
            return parse_llm_json(content), reasoning
        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            last_err = e
            if attempt + 1 < retries:
                time.sleep(1)  # 缓一秒再掷骰子
    log_abnormal("重试耗尽", user_msg.splitlines()[0][:40], str(last_err)[:200])
    raise last_err


def _validate(data: dict, mode: str, word: str, reasoning: str) -> None:
    """最小校验,防止模型抽风污染缓存;不过关就抛错,由 call_llm 重掷。"""
    if mode == "basic":
        for key in ("parents", "children", "similar"):
            assert isinstance(data.get(key), list), f"模型返回缺少 {key}"
        # 数量下限:提示词要 2~3/4~8/8~12,但只查字段会被"懒骰子"钻空子
        # (真出过 children=1/similar=0 的合法 JSON)。阈值定在正常水位一半,拦懒不冤好。
        n_p, n_c, n_s = len(data["parents"]), len(data["children"]), len(data["similar"])
        if n_p < 1 or n_c < 3 or n_s < 5:
            log_abnormal("漫游数据过稀", word, f"parents={n_p}/children={n_c}/similar={n_s}")
            raise AssertionError(f"漫游数据过稀(parents={n_p}/children={n_c}/similar={n_s}),重掷")
        data["thinking"] = reasoning  # 漫游也把思维链存下来,前端可单独查看
    elif mode == "deep":
        assert isinstance(data.get("dimensions"), list) and data["dimensions"], "模型返回缺少 dimensions"
        n_items = sum(len(d.get("items") or []) for d in data["dimensions"])
        if len(data["dimensions"]) < 3 or n_items < 8:
            log_abnormal("深挖数据过稀", word, f"{len(data['dimensions'])}个维度/共{n_items}条")
            raise AssertionError(f"深挖数据过稀({len(data['dimensions'])}个维度/共{n_items}条),重掷")
        data["thinking"] = reasoning  # 深挖把思维链一起存下来,前端可单独查看
    else:  # detail
        assert isinstance(data.get("detail"), str) and data["detail"].strip(), "模型返回缺少 detail"
        cap = DETAIL_CAP_CHARS[load_settings()["detail_len"]]
        assert len(data["detail"]) <= cap, f"解释超长({len(data['detail'])}字)"
        if not data["detail"].rstrip().endswith(END_PUNCT):
            # 句子结尾不是句号类标点:多半是话说一半(预算截断或模型自己断片)
            log_abnormal("详情疑似腰斩", word, f"结尾:{data['detail'][-60:]!r}")
            raise ValueError("详情话说一半,重掷一次")


def build_prompt(word: str, flavor: str, visited: list[str], mode: str = "basic", ctx: str = "") -> tuple:
    """拼出一次生成请求的三件套 (system, user, temperature)。
    在线请求和批量预热共用,保证两条路的提示词一字不差。"""
    visited_text = "、".join(visited[-40:]) if visited else "(还没有)"
    user_msg = f"关键词:{word}\n口味偏好:{flavor}\n已访问过(不要重复推荐):{visited_text}"
    s = load_settings()
    if s["blacklist"]:
        # 黑名单单独成行且永不截断——已访问只留最近40个,黑名单截掉了就会从别的词身上长回来
        user_msg += f"\n黑名单(用户明确不想再见,绝对不要推荐):{'、'.join(s['blacklist'])}"
    if ctx:
        user_msg += f"\n它出自的介绍片段:{ctx}"
    system = {"basic": SYSTEM_PROMPT, "deep": DEEP_SYSTEM_PROMPT,
              # 详情长度是用户设置:模板里的"150字"按档位替换(校验上限 DETAIL_CAP_CHARS 同步放宽)
              "detail": DETAIL_SYSTEM_PROMPT.replace("150", str(DETAIL_LEN_CHARS[s["detail_len"]]))}[mode]
    temp_map = TEMP_DETAIL if mode == "detail" else TEMP_ROAM
    temperature = temp_map[s["temp_style"]]  # 详情/追问求准,漫游求惊喜;幅度档位用户可调
    return system, user_msg, temperature


def call_llm(word: str, flavor: str, visited: list[str], mode: str = "basic", ctx: str = "") -> dict:
    """调 DeepSeek 生成扩展词。mode=basic 普通漫游,mode=deep 按类型深挖。
    ctx:输入所在的介绍片段,句式输入推断指向时用。
    校验不过(字段缺失/详情腰斩)自动重掷一次——温度高就是掷骰子,重掷通常就好。"""
    system, user_msg, temperature = build_prompt(word, flavor, visited, mode, ctx)

    last_err: Exception = ValueError("未执行")
    for _attempt in range(2):
        data, reasoning = chat(system, user_msg, temperature=temperature)
        try:
            _validate(data, mode, word, reasoning)
            return data
        except (AssertionError, ValueError) as e:
            last_err = e
    raise last_err
