"""测试脚手架:数据隔离 + 假 LLM 端点 + 网络闸门。

三条硬规矩(踩过坑才知道要立):
  1. **绝不打真实 API**。任何测试都用本地假端点;并且全局拦截 socket.connect,
     只放行 127.0.0.1 —— 万一哪天写错配置,测试会直接报错而不是花掉用户的钱。
  2. **绝不碰真实数据**。所有 load/save 都指向一次性临时目录,跑完删掉。
  3. 环境变量与数据目录必须在 import app/llm **之前**就位,因为 llm.py 在 import 时读环境。

跑法:
    python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STATIC = ROOT / 'static'          # sw.js 等静态文件从磁盘读,所以要指回真实目录

# ---------- 1. 数据隔离:临时目录代替 data/ ----------
TMP = Path(tempfile.mkdtemp(prefix='roam-test-'))
DATA = TMP / 'data'
DATA.mkdir(parents=True, exist_ok=True)

import store  # noqa: E402

store.BASE_DIR = TMP
store.CACHE_FILE = DATA / 'cache.json'
store.ASKS_FILE = DATA / 'asks.json'
store.NOTES_FILE = DATA / 'notes.json'
store.SETTINGS_FILE = DATA / 'settings.json'
store.LOG_FILE = DATA / 'abnormal.log'


# ---------- 2. 指向本地假端点(必须在 import app/llm 之前) ----------
STUB_PORT = 8791
os.environ.update({
    'LLM_BASE_URL': f'http://127.0.0.1:{STUB_PORT}/v1',
    'LLM_API_KEY': 'stub-key',
    'LLM_MODEL': 'stub-model',
})
os.environ.pop('DEEPSEEK_API_KEY', None)
os.environ.pop('DEEPSEEK_MODEL', None)


# ---------- 3. 假 LLM 端点:按提示词内容与词名给出可预测的答复 ----------
class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, obj, finish='stop'):
        body = json.dumps({'choices': [{'finish_reason': finish, 'message': obj}],
                           'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """/models:测试连接按钮走的就是这条(GET),不实现它 test-conn 会报 unknown。"""
        if self.path.endswith('/models'):
            body = json.dumps({'data': [{'id': 'stub-model'}, {'id': '另一个模型'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        req = json.loads(self.rfile.read(n) or b'{}')
        blob = json.dumps(req, ensure_ascii=False)
        user = next((m.get('content') or '' for m in req.get('messages', [])
                     if m.get('role') == 'user'), '')
        word = user.splitlines()[0].replace('关键词:', '').replace('中心词:', '').strip() or '测试词'
        mode = 'detail' if '词条解释器' in blob else ('deep' if '深挖引擎' in blob else
                                                      ('ask' if '追问助手' in blob else
                                                       ('chat' if '陪聊' in blob else 'basic')))

        if 'FAIL' in word:                     # 半句话 → 校验不过,用来测失败记账与退避
            det = f'{word}是一个很有意思的东西,它的故事要从很久以前说起,那时候'
            return self._reply({'content': json.dumps({'word': word, 'detail': det})})
        if 'DIRTY' in word:                    # 非 JSON → 测解析失败
            return self._reply({'content': '抱歉,我不太确定。'})
        if 'CUT' in word:                      # finish_reason=length → 测截断留痕
            return self._reply({'content': json.dumps({'word': word, 'detail': '话说一半'})}, finish='length')
        if 'EMPTY' in word:                    # 正文空但思维链有货 → 测兜底
            return self._reply({'content': '', 'reasoning_content': json.dumps({'word': word, 'detail': f'{word}的兜底解释。'})})

        if mode == 'detail':
            return self._reply({'content': json.dumps({'word': word, 'detail': f'{word}:这是一段完整、合格、以句号收尾的解释。'})})
        if mode == 'deep':
            dims = [{'name': f'维度{i}', 'items': [{'word': f'{word}子{i}-{j}', 'note': '注'} for j in range(3)]}
                    for i in range(3)]
            return self._reply({'content': json.dumps({'type': '技术', 'summary': f'{word}的一句话', 'dimensions': dims})})
        if mode == 'ask':
            return self._reply({'content': json.dumps({'answer': f'关于{word}的回答。'})})
        if mode == 'chat':
            return self._reply({'content': json.dumps({'answer': f'关于{word}的对话回答。'})})
        parents = [{'word': f'{word}上级{i}', 'note': '注'} for i in range(2)]
        children = [{'word': f'{word}下级{i}', 'note': '注'} for i in range(4)]
        similar = [{'word': f'{word}相邻{i}', 'note': '注'} for i in range(8)]
        return self._reply({'content': json.dumps({'word': word, 'parents': parents,
                                                   'children': children, 'similar': similar})})


class _StubServer(ThreadingHTTPServer):
    daemon_threads = True


_stub = _StubServer(('127.0.0.1', STUB_PORT), _StubHandler)
threading.Thread(target=_stub.serve_forever, daemon=True).start()

# ---------- 4. 网络闸门:只允许本地 ----------
_real_connect = socket.socket.connect


def _guarded_connect(self, address, *a, **kw):
    host = address[0] if isinstance(address, tuple) else str(address)
    if host not in ('127.0.0.1', 'localhost', '::1'):
        raise AssertionError(
            f'测试试图连接外网 {address!r} —— 测试永远不许打真实 API。'
            '请检查 settings.json / 环境变量是否把端点指到了真实供应商。')
    return _real_connect(self, address, *a, **kw)


socket.socket.connect = _guarded_connect


def _rmtree(path):
    shutil.rmtree(path, ignore_errors=True)


def _bind_app_static():
    """app.BASE_DIR 用来定位 static/(/sw.js 从磁盘发),得指回真实项目根;
    其余数据访问都走 store 里已改写过的路径,所以数据仍然是隔离的。"""
    import app as A
    A.BASE_DIR = ROOT
    return A


_bind_app_static()


import atexit  # noqa: E402

atexit.register(_rmtree, TMP)


# ---------- 给测试用的工具 ----------
CACHE_SEED = {
    '咖啡豆': {'word': '咖啡豆', 'time': 100, 'parents': [{'word': '咖啡文化', 'note': 'n'}],
               'children': [{'word': '阿拉比卡', 'note': 'n'}, {'word': '手冲咖啡', 'note': 'n'},
                            {'word': '意式浓缩', 'note': 'n'}, {'word': '咖啡烘焙', 'note': 'n'}],
               'similar': [{'word': '茶叶', 'note': 'n'}], 'detail': '咖啡豆的解释。'},
    '咖啡文化': {'word': '咖啡文化', 'time': 90, 'detail': '咖啡文化的解释。'},
    '阿拉比卡': {'word': '阿拉比卡', 'time': 80, 'detail': '阿拉比卡的解释。'},
    '手冲咖啡': {'word': '手冲咖啡', 'time': 70, 'parents': [{'word': '咖啡文化', 'note': 'n'}]},
    '意式浓缩': {'word': '意式浓缩', 'time': 60},
    '咖啡烘焙': {'word': '咖啡烘焙', 'time': 50},
    '茶叶': {'word': '茶叶', 'time': 40},
    '阿里巴巴': {'word': '阿里巴巴', 'time': 30,
                 'deep': {'type': '组织', 'summary': '电商巨头',
                          'dimensions': [{'name': '历史沿革', 'items': [
                              {'word': '湖畔花园创业', 'note': 'n'}, {'word': '中供铁军', 'note': 'n'},
                              {'word': '双十一', 'note': 'n'}]},
                              {'name': '关键人物', 'items': [
                                  {'word': '马云', 'note': 'n'}, {'word': '张勇', 'note': 'n'}]}]}},
    '马云': {'word': '马云', 'time': 20, 'detail': '马云的解释。'},
}


def reset_data(**files):
    """把临时数据目录重置成一份已知状态(每个测试开头调用)。"""
    for p in (store.CACHE_FILE, store.ASKS_FILE, store.NOTES_FILE,
              store.SETTINGS_FILE, store.LOG_FILE):
        if p.exists():
            p.unlink()
    _write(store.CACHE_FILE, files.get('cache', CACHE_SEED))
    if files.get('settings') is not None:
        _write(store.SETTINGS_FILE, files['settings'])
    if files.get('asks') is not None:
        _write(store.ASKS_FILE, files['asks'])
    if files.get('notes') is not None:
        _write(store.NOTES_FILE, files['notes'])


def seed_word(word: str, **extra):
    """把一个词条直接塞进缓存(模拟"这个词本来就在足迹里")。

    测试"详情反复失败"时必须先这么来一下 —— 失败记账刻意只对已存在的词条生效,
    不为失败凭空造足迹词条(见 store.record_detail_fail)。
    """
    cache = store.load_cache()
    cache[word] = {'word': word, 'time': int(__import__('time').time()), **extra}
    _write(store.CACHE_FILE, cache)
    return cache[word]


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding='utf-8')


def read_cache():
    return store.load_cache()


def read_log():
    return store.LOG_FILE.read_text(encoding='utf-8') if store.LOG_FILE.exists() else ''
