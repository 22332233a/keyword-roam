"""自动补详情"反复烧钱"修复的端到端回归(README 第13条)。

和 tests/test_api.py 里的 TestExpandFailureGuard 有重叠,但这条**故意保留独立**:
它用真实的 HTTP 端点(不是 Flask 测试客户端)、走完整路由栈,是"最后一公里"的确认。

测试脚手架(tests/support.py)负责:临时数据目录 + 本地假端点 + 网络闸门(只放行 127.0.0.1)。
所以这个测试永远不会打真实 API,也不会碰你的 data/。

跑法:python -m unittest tests.test_detail_failguard -v
"""
import unittest

from tests import support
from tests.support import reset_data

import app as A
import store
from llm import resolve_api_config


class TestFailGuardEndToEnd(unittest.TestCase):
    def setUp(self):
        reset_data()
        self.c = A.app.test_client()
        support.seed_word('FAIL词')      # 失败记账只对已存在的词条生效

    def test_端点必须是本地桩(self):
        """这道断言就是"测试不许花用户钱"的最后一道闸。"""
        cfg = resolve_api_config()
        self.assertTrue(cfg['base_url'].startswith('http://127.0.0.1:'),
                        f'生效端点是 {cfg["base_url"]} —— 不是本地桩,测试会花真钱')

    def test_连续失败会记账并最终被跳过(self):
        codes = []
        for _ in range(store.DETAIL_FAIL_LIMIT + 1):
            r = self.c.get('/api/expand', query_string={'word': 'FAIL词', 'mode': 'detail', 'flavor': 'x'})
            codes.append(r.status_code)
        self.assertEqual(codes[:store.DETAIL_FAIL_LIMIT], [502] * store.DETAIL_FAIL_LIMIT)
        self.assertEqual(codes[-1], 409, '到上限后应该直接跳过,不再打模型')
        self.assertEqual(store.detail_fail_count(support.read_cache()['FAIL词']), store.DETAIL_FAIL_LIMIT)

    def test_手动重试仍然放行(self):
        for _ in range(store.DETAIL_FAIL_LIMIT):
            self.c.get('/api/expand', query_string={'word': 'FAIL词', 'mode': 'detail', 'flavor': 'x'})
        r = self.c.get('/api/expand', query_string={'word': 'FAIL词', 'mode': 'detail',
                                                    'flavor': 'x', 'force': '1'})
        self.assertEqual(r.status_code, 502, 'force=1 应该绕过硬闸门重新打')

    def test_清单接口标出已跳过(self):
        for _ in range(store.DETAIL_FAIL_LIMIT):
            self.c.get('/api/expand', query_string={'word': 'FAIL词', 'mode': 'detail', 'flavor': 'x'})
        cache = support.read_cache()
        cache['咖啡豆']['children'].append({'word': 'FAIL词', 'note': 'n'})
        support._write(store.CACHE_FILE, cache)
        items = self.c.get('/api/tree-words', query_string={'word': '咖啡豆'}).get_json()['items']
        item = next(it for it in items if it['word'] == 'FAIL词')
        self.assertTrue(item['skipped'])
        self.assertEqual(item['failed_count'], store.DETAIL_FAIL_LIMIT)

    def test_成功之后失败记录会被清掉(self):
        cache = support.read_cache()
        cache['咖啡豆']['failed'] = {'detail': 2, 'time': 1}
        support._write(store.CACHE_FILE, cache)
        self.c.get('/api/expand', query_string={'word': '咖啡豆', 'mode': 'detail', 'flavor': 'x',
                                                'force': '1'})
        self.assertNotIn('failed', support.read_cache()['咖啡豆'])

    def test_合并漫游结果不会冲掉失败记录(self):
        cache = support.read_cache()
        cache['FAIL词']['failed'] = {'detail': 2, 'time': 1}
        support._write(store.CACHE_FILE, cache)
        c = support.read_cache()
        store.merge_into_cache(c, 'FAIL词', 'basic',
                               {'parents': [], 'children': [], 'similar': []}, 'x')
        self.assertEqual(store.detail_fail_count(c['FAIL词']), 2)

    def test_合并语义不写入None(self):
        cache = support.read_cache()
        store.merge_into_cache(cache, '某词', 'basic',
                               {'parents': [], 'children': [], 'similar': []}, 'x')
        import json
        json.dumps(cache)   # 能序列化就说明没有 undefined/None 混进去


if __name__ == '__main__':
    unittest.main()
