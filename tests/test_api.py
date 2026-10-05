"""app.py:/api/* 路由的行为与错误分类。

用 Flask 测试客户端 + 本地假端点,全程不出网。
"""
import json
import unittest

from tests import support
from tests.support import reset_data

import app as A
import llm
import store


class ApiCase(unittest.TestCase):
    def setUp(self):
        reset_data()
        self.c = A.app.test_client()

    def expand(self, word, **kw):
        q = {'word': word, 'flavor': 'x'}
        q.update(kw)
        r = self.c.get('/api/expand', query_string=q)
        return r.status_code, (r.get_json() or {})


class TestExpandCaching(ApiCase):
    def test_已有漫游树直接吃缓存不花钱(self):
        code, b = self.expand('咖啡豆', mode='basic')
        self.assertEqual(code, 200)
        self.assertTrue(b['cached'])
        self.assertEqual(len(b['data']['parents']), 1)

    def test_只有详情没有漫游树时basic不给数据(self):
        """深挖-only 的词就是走这条:404,并且要告诉前端"有没有深挖"。"""
        code, b = self.expand('阿里巴巴', mode='basic', cache_only='1')
        self.assertEqual(code, 404)
        self.assertTrue(b['no_roam'])
        self.assertTrue(b['word_exists'])
        self.assertTrue(b['has_deep'], '有深挖树却报 has_deep=false,前端就挂不出补详情入口')

    def test_压根没这个词时has_deep为假(self):
        code, b = self.expand('从没听过的词', mode='basic', cache_only='1')
        self.assertEqual(code, 404)
        self.assertFalse(b['word_exists'])
        self.assertFalse(b['has_deep'])

    def test_深挖命中缓存(self):
        reset_data(cache={'某词': {'word': '某词', 'time': 1, 'deep': {'type': '人物', 'dimensions': []}}})
        code, b = self.expand('某词', mode='deep')
        self.assertEqual(code, 200)
        self.assertTrue(b['cached'])
        self.assertEqual(b['data']['type'], '人物')

    def test_详情命中缓存(self):
        code, b = self.expand('马云', mode='detail')
        self.assertEqual(code, 200)
        self.assertTrue(b['cached'])
        self.assertEqual(b['data']['detail'], '马云的解释。')

    def test_新词会真的生成并入库(self):
        code, b = self.expand('新词', mode='basic')
        self.assertEqual(code, 200)
        self.assertFalse(b['cached'])
        self.assertIn('新词', support.read_cache(), '生成成功却没入库')

    def test_force跳过缓存重掷(self):
        code, b = self.expand('咖啡豆', mode='basic', force='1')
        self.assertEqual(code, 200)
        self.assertFalse(b['cached'], 'force=1 应该无视缓存')

    def test_参数校验(self):
        self.assertEqual(self.expand('', mode='basic')[0], 400)
        self.assertEqual(self.expand('字' * 40, mode='basic')[0], 400)
        self.assertEqual(self.expand('词', mode='不存在的模式')[0], 400)


class TestExpandFailureGuard(ApiCase):
    """连续生成不出来的词不再被自动补详情反复烧钱(见 README 第13条)。

    注意:失败记账只对"已经存在的词条"生效(不为失败凭空造足迹词条),
    所以这里先用 support.seed_word 把 FAIL词 放进足迹,模拟真实的"漫游到过它"。
    """

    def setUp(self):
        super().setUp()
        support.seed_word('FAIL词')

    def test_失败会记账(self):
        for i in (1, 2, 3):
            code, _ = self.expand('FAIL词', mode='detail')
            self.assertEqual(code, 502)
            self.assertEqual(store.detail_fail_count(support.read_cache().get('FAIL词')), i)

    def test_到上限后返回409且不打模型(self):
        for _ in range(store.DETAIL_FAIL_LIMIT):
            self.expand('FAIL词', mode='detail')
        code, b = self.expand('FAIL词', mode='detail')
        self.assertEqual(code, 409)
        self.assertTrue(b['skipped'])
        self.assertEqual(b['failed_count'], store.DETAIL_FAIL_LIMIT)

    def test_手动重试仍可打(self):
        for _ in range(store.DETAIL_FAIL_LIMIT):
            self.expand('FAIL词', mode='detail')
        code, _ = self.expand('FAIL词', mode='detail', force='1')
        self.assertEqual(code, 502, 'force=1 应该绕过硬闸门')

    def test_网络类失败不记账(self):
        """端点抖动不等于"这个词不行",不该消耗退避额度。"""
        cfg = llm.resolve_api_config
        try:
            llm.resolve_api_config = lambda *a, **k: {'base_url': 'http://127.0.0.1:9/v1',
                                                      'api_key': 'k', 'model': 'm',
                                                      'max_tokens': 100, 'key_from': 'settings'}
            code, _ = self.expand('咖啡豆', mode='detail', force='1')
            self.assertEqual(code, 502)
            self.assertEqual(store.detail_fail_count(support.read_cache().get('咖啡豆')), 0)
        finally:
            llm.resolve_api_config = cfg

    def test_生成成功后清掉失败记账(self):
        cache = support.read_cache()
        cache['咖啡豆']['failed'] = {'detail': 3, 'time': 1}
        support._write(store.CACHE_FILE, cache)
        self.expand('咖啡豆', mode='detail')          # 命中缓存即可触发清理
        self.assertNotIn('failed', support.read_cache()['咖啡豆'])

    def test_失败记账不为新词造足迹(self):
        """回到上面那条前提:词条不存在时只报错,不写缓存。"""
        self.expand('从未见过的FAIL词', mode='detail')
        self.assertNotIn('从未见过的FAIL词', support.read_cache())


class TestTreeAndDeepWords(ApiCase):
    def test_tree_words列出漫游与深挖并标注状态(self):
        code, _ = self.expand('FAIL词', mode='detail')
        b = self.c.get('/api/tree-words', query_string={'word': '咖啡豆'}).get_json()
        items = {it['word']: it for it in b['items']}
        self.assertIn('阿拉比卡', items)
        self.assertTrue(items['阿拉比卡']['has_detail'])
        self.assertFalse(items['咖啡烘焙']['has_detail'])
        self.assertEqual(items['咖啡烘焙']['grp'], 'roam')

    def test_tree_words标出被跳过的词(self):
        support.seed_word('FAIL词')
        for _ in range(store.DETAIL_FAIL_LIMIT):
            self.expand('FAIL词', mode='detail')
        cache = support.read_cache()
        cache['咖啡豆']['children'].append({'word': 'FAIL词', 'note': 'n'})
        support._write(store.CACHE_FILE, cache)
        b = self.c.get('/api/tree-words', query_string={'word': '咖啡豆'}).get_json()
        item = next(it for it in b['items'] if it['word'] == 'FAIL词')
        self.assertTrue(item['skipped'])
        self.assertEqual(item['failed_count'], store.DETAIL_FAIL_LIMIT)

    def test_tree_words排掉黑名单(self):
        support._write(store.SETTINGS_FILE, {'blacklist': ['咖啡烘焙']})
        b = self.c.get('/api/tree-words', query_string={'word': '咖啡豆'}).get_json()
        item = next(it for it in b['items'] if it['word'] == '咖啡烘焙')
        self.assertTrue(item['black'])

    def test_deep_words只挑深挖树里缺详情的(self):
        b = self.c.get('/api/deep-words', query_string={'word': '阿里巴巴'}).get_json()
        self.assertEqual(b['trees'], 1)
        self.assertEqual(sorted(b['missing']), ['中供铁军', '双十一', '张勇', '湖畔花园创业'])
        self.assertNotIn('马云', b['missing'], '已有详情的词不该进清单')

    def test_deep_words扫全部深挖树(self):
        b = self.c.get('/api/deep-words').get_json()
        self.assertGreaterEqual(b['trees'], 1)
        self.assertEqual(b['scope'], '(全部深挖树)')

    def test_deep_words对没有深挖的词返回空(self):
        b = self.c.get('/api/deep-words', query_string={'word': '咖啡豆'}).get_json()
        self.assertEqual(b['count'], 0)
        self.assertEqual(b['trees'], 0)

    def test_deep_words排掉黑名单与被跳过的词(self):
        support.seed_word('FAIL词')
        for _ in range(store.DETAIL_FAIL_LIMIT):
            self.expand('FAIL词', mode='detail')
        cache = support.read_cache()
        cache['阿里巴巴']['deep']['dimensions'][0]['items'].append({'word': 'FAIL词', 'note': 'n'})
        cache['阿里巴巴']['deep']['dimensions'][0]['items'].append({'word': '马云', 'note': 'n'})
        support._write(store.CACHE_FILE, cache)
        support._write(store.SETTINGS_FILE, {'blacklist': ['马云']})
        b = self.c.get('/api/deep-words', query_string={'word': '阿里巴巴'}).get_json()
        self.assertNotIn('FAIL词', b['missing'])
        self.assertEqual(b['skipped'], 1)
        self.assertNotIn('马云', b['missing'], '黑名单词不该进清单')


class TestCacheAndGraph(ApiCase):
    def test_cache带功能标记(self):
        b = self.c.get('/api/cache').get_json()
        it = next(x for x in b['words'] if x['word'] == '咖啡豆')
        self.assertIn('roam', it['feats'])
        self.assertIn('detail', it['feats'])
        self.assertEqual(it['failed'], 0)

    def test_cache带上失败次数(self):
        support.seed_word('FAIL词')          # 失败记账只对已存在的词条生效
        for _ in range(2):
            self.expand('FAIL词', mode='detail')
        b = self.c.get('/api/cache').get_json()
        it = next((x for x in b['words'] if x['word'] == 'FAIL词'), None)
        self.assertIsNotNone(it, '失败记账不该把词条漏掉')
        self.assertEqual(it['failed'], 2)

    def test_cache按最近排序(self):
        words = [x['word'] for x in self.c.get('/api/cache').get_json()['words']]
        times = [x['time'] for x in self.c.get('/api/cache').get_json()['words']]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_graph节点与边(self):
        b = self.c.get('/api/graph').get_json()
        self.assertIn('咖啡豆', [n['word'] for n in b['nodes']])
        self.assertTrue(any(e['a'] == '咖啡豆' or e['b'] == '咖啡豆' for e in b['edges']))
        self.assertIn('咖啡豆', json.dumps(b, ensure_ascii=False))


class TestSettingsApi(ApiCase):
    def test_get掩码key(self):
        support._write(store.SETTINGS_FILE, {'api': {'key': 'sk-abcdefghijklmnop'}})
        b = self.c.get('/api/settings').get_json()
        self.assertTrue(b['api']['has_key'])
        self.assertNotIn('key', b['api'])
        self.assertEqual(b['api']['key_preview'], 'sk-a…mnop')

    def test_post非法档位被拒(self):
        self.assertEqual(self.c.post('/api/settings', json={'detail_len': '超长'}).status_code, 400)
        self.assertEqual(self.c.post('/api/settings', json={'temp_style': '疯'}).status_code, 400)
        self.assertEqual(self.c.post('/api/settings', json={'auto_detail': '随便'}).status_code, 400)

    def test_post部分更新不动其他键(self):
        self.c.post('/api/settings', json={'detail_len': '长'})
        support._write(store.SETTINGS_FILE, {**store.load_settings(), 'temp_style': '抽风'})
        self.c.post('/api/settings', json={'detail_len': '短'})
        s = store.load_settings()
        self.assertEqual(s['detail_len'], '短')
        self.assertEqual(s['temp_style'], '抽风')

    def test_post空key不改动已有key(self):
        support._write(store.SETTINGS_FILE, {'api': {'key': 'sk-old'}})
        self.c.post('/api/settings', json={'api': {'key': ''}})
        self.assertEqual(store.load_settings()['api']['key'], 'sk-old')

    def test_post哨兵值清除key(self):
        support._write(store.SETTINGS_FILE, {'api': {'key': 'sk-old'}})
        self.c.post('/api/settings', json={'api': {'key': store.KEY_CLEAR}})
        self.assertEqual(store.load_settings()['api']['key'], '')


class TestNoteApi(ApiCase):
    def test_写读删笔记(self):
        self.c.post('/api/note', json={'word': '咖啡豆', 'text': '记一笔'})
        self.assertEqual(self.c.get('/api/note', query_string={'word': '咖啡豆'}).get_json()['text'], '记一笔')
        self.c.post('/api/note', json={'word': '咖啡豆', 'text': '   '})
        self.assertEqual(self.c.get('/api/note', query_string={'word': '咖啡豆'}).get_json()['text'], '',
                         '清空应该删条目,而不是留一条空笔记')

    def test_缺词报400(self):
        self.assertEqual(self.c.post('/api/note', json={'text': 'x'}).status_code, 400)


class TestAskAndChat(ApiCase):
    def test_追问进缓存(self):
        code, b = self.expand('咖啡豆', mode='basic')
        r = self.c.get('/api/ask', query_string={'word': '咖啡豆', 'q': '为什么'}).get_json()
        self.assertFalse(r['cached'])
        r2 = self.c.get('/api/ask', query_string={'word': '咖啡豆', 'q': '为什么'}).get_json()
        self.assertTrue(r2['cached'], '同样的问题不该花第二次钱')

    def test_追问参数校验(self):
        self.assertEqual(self.c.get('/api/ask', query_string={'word': 'w', 'q': ''}).status_code, 400)
        self.assertEqual(self.c.get('/api/ask', query_string={'word': 'w', 'q': '字' * 120}).status_code, 400)

    def test_对话正常返回(self):
        r = self.c.post('/api/chat', json={'word': '咖啡豆', 'q': '讲讲', 'ctx': '上下文'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('对话回答', r.get_json()['data']['answer'])

    def test_对话参数校验(self):
        self.assertEqual(self.c.post('/api/chat', json={'word': 'w', 'q': ''}).status_code, 400)


class TestIndexAndServiceWorker(ApiCase):
    def test_首页可渲染(self):
        r = self.c.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('关键词漫游器', r.get_data(as_text=True))

    def test_sw从根路径提供并放开作用域(self):
        r = self.c.get('/sw.js')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get('Service-Worker-Allowed'), '/',
                         '缺这个头,service worker 作用域会被限死在 /static/')
        self.assertIn('no-cache', r.headers.get('Cache-Control', ''))

    def test_sw清单里的静态文件都真实存在(self):
        """sw.js 的 SHELL 列表是手写的:漏一个文件,离线外壳就残一块。"""
        import re
        text = (support.STATIC / 'sw.js').read_text(encoding='utf-8')
        urls = re.findall(r"^\s*'(/[^']+)',", text, re.M)
        self.assertTrue(urls, '没解析出 SHELL 清单,测试该更新了')
        for u in urls:
            if u == '/':
                continue
            self.assertTrue((support.STATIC.parent / u.lstrip('/')).exists(), f'sw.js 清单里的 {u} 不存在')


class TestTestConn(ApiCase):
    def test_连通时给出模型清单(self):
        r = self.c.post('/api/test-conn', json={}).get_json()
        self.assertTrue(r['ok'])
        self.assertEqual(r['key_from'], 'env')
        self.assertIn('stub-model', r['models'])
        self.assertTrue(r['model_listed'])

    def test_缺key时分类为missing_key(self):
        """设置里没 key、环境也没 key 时,要报 missing_key 而不是含糊的 unknown。"""
        env_key = llm.ENV_API_KEY
        try:
            llm.ENV_API_KEY = ''
            r = self.c.post('/api/test-conn', json={'api': {'base_url': 'https://api.deepseek.com'}}).get_json()
            self.assertFalse(r['ok'])
            self.assertEqual(r['reason'], 'missing_key')
            self.assertEqual(r['key_from'], 'none')
            self.assertIn('Key', r['hint'])
        finally:
            llm.ENV_API_KEY = env_key

    def test_缺key提示只在官方端点出现(self):
        self.assertTrue(llm.missing_key_hint({'api_key': '', 'base_url': 'https://api.deepseek.com'}))
        self.assertIsNone(llm.missing_key_hint({'api_key': '', 'base_url': 'http://localhost:11434/v1'}),
                          '本地端点不该被 key 检查拦住')

    def test_模型名不在列表会提示(self):
        r = self.c.post('/api/test-conn', json={'api': {'model': '不存在的模型'}}).get_json()
        self.assertTrue(r['ok'])
        self.assertFalse(r['model_listed'])

    def test_连不上时分类为connection(self):
        r = self.c.post('/api/test-conn', json={'api': {'base_url': 'http://127.0.0.1:9/v1'}}).get_json()
        self.assertFalse(r['ok'])
        self.assertIn(r['reason'], ('connection', 'timeout'))


class TestExport(ApiCase):
    def test_json备份含cache但不含key(self):
        support._write(store.SETTINGS_FILE, {'api': {'key': 'sk-secret-abcdefg'}})
        text = self.c.get('/api/export?format=json').get_data(as_text=True)
        data = json.loads(text)
        self.assertIn('咖啡豆', data['cache'])
        self.assertNotIn('sk-secret-abcdefg', text, '导出里出现了 key 明文')

    def test_markdown可读词表(self):
        text = self.c.get('/api/export?format=md').get_data(as_text=True)
        self.assertIn('# 关键词漫游足迹', text)
        self.assertIn('咖啡豆', text)

    def test_只导笔记(self):
        self.c.post('/api/note', json={'word': '咖啡豆', 'text': '笔记内容'})
        text = self.c.get('/api/export?what=notes&format=md').get_data(as_text=True)
        self.assertIn('笔记内容', text)
        data = json.loads(self.c.get('/api/export?what=notes&format=json').get_data(as_text=True))
        self.assertIn('咖啡豆', data['notes'])
        self.assertNotIn('cache', data)


if __name__ == '__main__':
    unittest.main()
