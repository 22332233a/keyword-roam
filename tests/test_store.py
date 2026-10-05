"""store.py:四份 JSON 的读写、设置规范化、合并语义。

这里是最该有测试的地方 —— 合并语义写错会静默吃掉用户已生成的数据。
"""
import json
import unittest

from tests import support                      # 脚手架:数据隔离 + 假端点 + 网络闸门
from tests.support import reset_data

import store


class TestJsonBase(unittest.TestCase):
    def setUp(self):
        reset_data()

    def test_缺失文件落回默认值(self):
        store.NOTES_FILE.unlink(missing_ok=True)
        self.assertEqual(store.load_notes(), {})

    def test_损坏的JSON不抛错只落回默认值(self):
        store.NOTES_FILE.write_text('{坏掉的 json', encoding='utf-8')
        self.assertEqual(store.load_notes(), {})

    def test_写入能读回(self):
        store.save_notes({'a': {'text': '你好'}})
        self.assertEqual(store.load_notes()['a']['text'], '你好')

    def test_写入自动建父目录(self):
        store.NOTES_FILE = store.NOTES_FILE.parent / 'sub' / 'notes.json'
        try:
            store.save_notes({'a': 1})
            self.assertTrue(store.NOTES_FILE.exists())
        finally:
            store.NOTES_FILE = support.DATA / 'notes.json'


class TestMergeIntoCache(unittest.TestCase):
    def setUp(self):
        reset_data()

    def test_basic整条写入并带上word_flavor_time(self):
        cache = {}
        store.merge_into_cache(cache, '新词', 'basic',
                               {'parents': [{'word': 'p'}], 'children': [], 'similar': []}, '口味')
        e = cache['新词']
        self.assertEqual(e['word'], '新词')
        self.assertEqual(e['flavor'], '口味')
        self.assertIsInstance(e['time'], int)

    def test_basic不冲掉已有深挖与详情(self):
        cache = {'旧词': {'word': '旧词', 'deep': {'type': 'X'}, 'detail': '旧详情',
                          'failed': {'detail': 2, 'time': 1}}}
        store.merge_into_cache(cache, '旧词', 'basic',
                               {'parents': [], 'children': [], 'similar': []}, 'f')
        e = cache['旧词']
        self.assertEqual(e['deep'], {'type': 'X'}, '深挖被 basic 覆盖了')
        self.assertEqual(e['detail'], '旧详情', '详情被 basic 覆盖了')
        self.assertEqual(e['failed']['detail'], 2, '失败记账被 basic 冲掉了')

    def test_detail写入并清掉失败记账(self):
        cache = {'词': {'word': '词', 'parents': [{'word': 'p'}], 'failed': {'detail': 3, 'time': 1}}}
        store.merge_into_cache(cache, '词', 'detail', {'word': '词', 'detail': '新详情'})
        self.assertEqual(cache['词']['detail'], '新详情')
        self.assertEqual(cache['词']['parents'], [{'word': 'p'}], '漫游树被详情冲掉了')
        self.assertNotIn('failed', cache['词'], '生成成功后失败记账该清掉')

    def test_deep写入保留漫游与详情(self):
        cache = {'词': {'word': '词', 'parents': [{'word': 'p'}], 'detail': '旧'}}
        store.merge_into_cache(cache, '词', 'deep', {'type': '人物', 'dimensions': []})
        self.assertEqual(cache['词']['deep']['type'], '人物')
        self.assertEqual(cache['词']['parents'], [{'word': 'p'}])
        self.assertEqual(cache['词']['detail'], '旧')

    def test_detail给不存在的词也能建条(self):
        cache = {}
        store.merge_into_cache(cache, '新词', 'detail', {'word': '新词', 'detail': '解释'})
        self.assertEqual(cache['新词']['detail'], '解释')
        self.assertIn('time', cache['新词'])

    def test_不写入undefined等非JSON值(self):
        cache = {'词': {'word': '词'}}
        store.merge_into_cache(cache, '词', 'basic', {'parents': [], 'children': [], 'similar': []}, '')
        json.dumps(cache)   # 能序列化 = 没有 undefined/NaN 之类


class TestDetailFailCounter(unittest.TestCase):
    def setUp(self):
        reset_data()

    def test_没有记录时返回0(self):
        self.assertEqual(store.detail_fail_count({}), 0)
        self.assertEqual(store.detail_fail_count(None), 0)
        self.assertEqual(store.detail_fail_count({'failed': '垃圾'}), 0)

    def test_失败递增(self):
        cache = {'词': {'word': '词'}}
        self.assertEqual(store.record_detail_fail(cache, '词'), 1)
        self.assertEqual(store.record_detail_fail(cache, '词'), 2)
        self.assertEqual(store.detail_fail_count(cache['词']), 2)

    def test_不给不存在的词凭空造条(self):
        cache = {}
        self.assertEqual(store.record_detail_fail(cache, '从没见过的词'), 0)
        self.assertEqual(cache, {}, '失败记账不该污染足迹词表')

    def test_清除记账(self):
        cache = {'词': {'word': '词', 'failed': {'detail': 3, 'time': 1}}}
        self.assertTrue(store.clear_detail_fail(cache, '词'))
        self.assertNotIn('failed', cache['词'])
        self.assertFalse(store.clear_detail_fail(cache, '词'), '没记录时返回 False')


class TestSettings(unittest.TestCase):
    def setUp(self):
        reset_data()

    def test_无设置文件时全默认(self):
        s = store.load_settings()
        self.assertEqual(s['detail_len'], '标准')
        self.assertEqual(s['auto_detail'], 'smart')
        self.assertEqual(s['api']['key'], '')

    def test_非法档位回落默认(self):
        support._write(store.SETTINGS_FILE, {'detail_len': '超长', 'temp_style': '疯',
                                             'auto_detail': '随便'})
        s = store.load_settings()
        self.assertEqual(s['detail_len'], '标准')
        self.assertEqual(s['temp_style'], '标准')
        self.assertEqual(s['auto_detail'], 'smart')

    def test_黑名单与口味被清洗(self):
        support._write(store.SETTINGS_FILE, {'blacklist': [' 词 ', '', None, 123],
                                             'flavors': [' 口味 ', None, 42]})
        s = store.load_settings()
        # 现值语义:列表项一律 str() 后去空白,非字符串会被转成 "None"/"42"。
        # 这条测试把现状钉住 —— 哪天想改成"丢掉非字符串",这里会红,逼你确认是改行为还是改测试。
        self.assertEqual(s['blacklist'], ['词', 'None', '123'])
        self.assertEqual(s['flavors'], ['口味', 'None', '42'])

    def test_黑名单有上限(self):
        support._write(store.SETTINGS_FILE, {'blacklist': [f'词{i}' for i in range(500)]})
        self.assertEqual(len(store.load_settings()['blacklist']), 200)

    def test_api数值字段非法值被清空(self):
        support._write(store.SETTINGS_FILE, {'api': {'max_tokens': 'abc', 'temperature': '9'}})
        a = store.load_settings()['api']
        self.assertEqual(a['max_tokens'], '')
        self.assertEqual(a['temperature'], '')

    def test_api_max_tokens范围校验(self):
        support._write(store.SETTINGS_FILE, {'api': {'max_tokens': '999999'}})
        self.assertEqual(store.load_settings()['api']['max_tokens'], '')
        support._write(store.SETTINGS_FILE, {'api': {'max_tokens': '8000'}})
        self.assertEqual(store.load_settings()['api']['max_tokens'], '8000')

    def test_合并api时空key表示别动(self):
        cur = {'base_url': '', 'key': '原key', 'model': '', 'temperature': '', 'max_tokens': ''}
        got = store.merge_api_settings(cur, {'key': ''})
        self.assertEqual(got['key'], '原key', '前端拿不到明文,空串必须是"别动"')

    def test_合并api时哨兵值表示清除(self):
        cur = {'base_url': '', 'key': '原key', 'model': '', 'temperature': '', 'max_tokens': ''}
        got = store.merge_api_settings(cur, {'key': store.KEY_CLEAR})
        self.assertEqual(got['key'], '')

    def test_合并api时新key写入(self):
        cur = store.DEFAULT_SETTINGS['api']
        got = store.merge_api_settings(cur, {'key': 'sk-new'})
        self.assertEqual(got['key'], 'sk-new')

    def test_快照永不回传key明文(self):
        snap = store.api_snapshot({'api': {'key': 'sk-abcdefghijklmn', 'base_url': 'x'}})
        self.assertNotIn('key', snap, 'key 原文绝不能出现在给前端的快照里')
        self.assertTrue(snap['has_key'])
        self.assertEqual(snap['key_preview'], 'sk-a…klmn')

    def test_掩码短key不透明文(self):
        self.assertEqual(store.mask_secret('short'), '…')
        self.assertEqual(store.mask_secret(''), '')
        self.assertEqual(store.mask_secret('sk-1234567890'), 'sk-1…7890')


class TestAbnormalLog(unittest.TestCase):
    def setUp(self):
        reset_data()

    def test_留痕格式(self):
        store.log_abnormal('类型', '谁', '细节')
        line = support.read_log().strip()
        self.assertIn('类型', line)
        self.assertIn('谁', line)
        self.assertIn('细节', line)
        self.assertEqual(line.count('|'), 2, '格式应为 [时间] 类型 | 谁 | 细节')

    def test_多线程同时写不会串行(self):
        import threading
        ts = [threading.Thread(target=store.log_abnormal, args=('K', f'w{i}', 'd')) for i in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        lines = support.read_log().strip().splitlines()
        self.assertEqual(len(lines), 20)
        for ln in lines:
            self.assertEqual(ln.count('|'), 2, f'行被写串了: {ln!r}')


if __name__ == '__main__':
    unittest.main()
