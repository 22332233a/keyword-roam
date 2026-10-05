"""llm.py:提示词拼装、JSON 解析、校验规则、配置解析、断引语抢救。

这些规则是"数据进不进缓存"的闸门,错一条就会污染用户的足迹。
"""
import unittest

from tests import support                      # 脚手架:数据隔离 + 假端点 + 网络闸门
from tests.support import reset_data

import llm
import store


class TestParseLlmJson(unittest.TestCase):
    def setUp(self):
        reset_data()

    def test_纯JSON(self):
        self.assertEqual(llm.parse_llm_json('{"a":1}'), {'a': 1})

    def test_容忍markdown围栏(self):
        self.assertEqual(llm.parse_llm_json('```json\n{"a":1}\n```'), {'a': 1})

    def test_容忍前后废话(self):
        self.assertEqual(llm.parse_llm_json('好的,这是结果:{"a":1} 以上。'), {'a': 1})

    def test_绕路解析会留痕(self):
        llm.parse_llm_json('废话{"a":1}废话')
        self.assertIn('JSON绕路解析', support.read_log())

    def test_没有JSON就抛错(self):
        with self.assertRaises(Exception):
            llm.parse_llm_json('完全没有 JSON')


class TestValidateDetail(unittest.TestCase):
    def setUp(self):
        reset_data()
        self.s = store.load_settings()

    def test_合格详情通过(self):
        llm._validate({'detail': '这是一段合格的解释。'}, 'detail', 'w', '')

    def test_缺detail字段报错(self):
        with self.assertRaises(AssertionError):
            llm._validate({}, 'detail', 'w', '')

    def test_空detail报错(self):
        with self.assertRaises(AssertionError):
            llm._validate({'detail': '   '}, 'detail', 'w', '')

    def test_超长报错(self):
        cap = store.DETAIL_CAP_CHARS[self.s['detail_len']]
        with self.assertRaises(AssertionError):
            llm._validate({'detail': '字' * (cap + 1)}, 'detail', 'w', '')

    def test_刚好卡在上限通过(self):
        cap = store.DETAIL_CAP_CHARS[self.s['detail_len']]
        llm._validate({'detail': '字' * (cap - 1) + '。'}, 'detail', 'w', '')

    def test_腰斩报错并留痕(self):
        with self.assertRaises(ValueError):
            llm._validate({'detail': '话说到一半就'}, 'detail', 'w', '')
        self.assertIn('详情疑似腰斩', support.read_log())

    def test_各种合法收尾标点都算通过(self):
        for end in ('。', '！', '？', '…', '」', '')[:-1]:
            llm._validate({'detail': f'一句完整的话{end}'}, 'detail', 'w', '')

    def test_尾部空白不影响判定(self):
        llm._validate({'detail': '一句完整的话。   \n\t '}, 'detail', 'w', '')


class TestValidateBasicAndDeep(unittest.TestCase):
    def setUp(self):
        reset_data()

    def test_basic合格(self):
        d = {'parents': [{'word': 'p'}], 'children': [{'word': 'c'}] * 3, 'similar': [{'word': 's'}] * 5}
        llm._validate(d, 'basic', 'w', '思考')
        self.assertEqual(d['thinking'], '思考', '漫游该把思维链存下来')

    def test_basic过稀报错并留痕(self):
        with self.assertRaises(AssertionError):
            llm._validate({'parents': [], 'children': [{'word': 'c'}] * 3, 'similar': [{'word': 's'}] * 5},
                          'basic', 'w', '')
        self.assertIn('漫游数据过稀', support.read_log())

    def test_basic缺字段报错(self):
        with self.assertRaises(AssertionError):
            llm._validate({'parents': []}, 'basic', 'w', '')

    def test_deep合格(self):
        d = {'dimensions': [{'name': 'x', 'items': [{'word': 'a'}] * 4}] * 3}
        llm._validate(d, 'deep', 'w', '思考')
        self.assertEqual(d['thinking'], '思考')

    def test_deep过稀报错(self):
        with self.assertRaises(AssertionError):
            llm._validate({'dimensions': [{'name': 'x', 'items': [{'word': 'a'}]}]}, 'deep', 'w', '')
        self.assertIn('深挖数据过稀', support.read_log())


class TestRepairDanglingQuote(unittest.TestCase):
    """断在引号里的"假收尾":模型主动结束 JSON 但句子停在引号上。"""

    def test_该救的救(self):
        d = {'detail': '用AI克隆孙燕姿音色翻唱,2023年在B站走红,她本人发文感叹"'}
        self.assertTrue(llm._repair(d))
        self.assertTrue(d['detail'].endswith('。'))
        self.assertNotIn('"', d['detail'])

    def test_正常内容一个字节都不动(self):
        for s in ('这是完整的一句话。', '带「引号」但正常收尾。', '结尾是问号？'):
            d = {'detail': s}
            self.assertFalse(llm._repair(d), f'不该动: {s}')
            self.assertEqual(d['detail'], s)

    def test_砍完太短就不救(self):
        d = {'detail': '短句说"'}
        self.assertFalse(llm._repair(d))
        self.assertEqual(d['detail'], '短句说"')

    def test_真腰斩不命中(self):
        d = {'detail': '2023年爆红的AI翻唱现象,网友拿孙燕姿几十小时的歌声当素材,让'}
        self.assertFalse(llm._repair(d), '断在"让"是真空话一半,该交给重掷')

    def test_空内容不炸(self):
        self.assertFalse(llm._repair({}))
        self.assertFalse(llm._repair({'detail': ''}))


class TestBuildPrompt(unittest.TestCase):
    def setUp(self):
        reset_data()

    def test_三种模式的system不同(self):
        sys_b, _, _ = llm.build_prompt('w', 'f', [], 'basic')
        sys_d, _, _ = llm.build_prompt('w', 'f', [], 'deep')
        sys_det, _, _ = llm.build_prompt('w', 'f', [], 'detail')
        self.assertEqual(len({sys_b, sys_d, sys_det}), 3)

    def test_详情字数按档位替换(self):
        support._write(store.SETTINGS_FILE, {'detail_len': '短'})
        sys_p, _, _ = llm.build_prompt('w', 'f', [], 'detail')
        self.assertIn(str(store.DETAIL_LEN_CHARS['短']), sys_p)
        self.assertNotIn('150', sys_p)

    def test_温度按档位(self):
        support._write(store.SETTINGS_FILE, {'temp_style': '稳'})
        self.assertEqual(llm.build_prompt('w', 'f', [], 'detail')[2], store.TEMP_DETAIL['稳'])
        self.assertEqual(llm.build_prompt('w', 'f', [], 'basic')[2], store.TEMP_ROAM['稳'])

    def test_黑名单进提示词且不截断(self):
        many = [f'黑词{i}' for i in range(50)]
        support._write(store.SETTINGS_FILE, {'blacklist': many})
        _, user, _ = llm.build_prompt('w', 'f', [], 'basic')
        self.assertIn('黑词49', user, '黑名单被截断了,会从别的词身上长回来')

    def test_已访问词只留最近40个(self):
        _, user, _ = llm.build_prompt('w', 'f', [f'词{i}' for i in range(100)], 'basic')
        self.assertNotIn('词0、', user)
        self.assertIn('词99', user)

    def test_ctx进提示词(self):
        _, user, _ = llm.build_prompt('w', 'f', [], 'detail', ctx='某段介绍')
        self.assertIn('某段介绍', user)

    def test_详情提示词不含引号示范(self):
        """踩过的坑:提示词里的引文示范会诱导模型写到引号就停(实测失败率 5/6)。"""
        s = llm.DETAIL_SYSTEM_PROMPT
        self.assertNotIn('某某 2014 年上线', s)
        self.assertIn('不要引述真实人物说过的话', s)


class TestResolveApiConfig(unittest.TestCase):
    def setUp(self):
        reset_data()

    def test_设置优先于环境(self):
        support._write(store.SETTINGS_FILE, {'api': {'base_url': 'https://设置端点', 'key': '设置key',
                                                     'model': '设置模型'}})
        cfg = llm.resolve_api_config()
        self.assertEqual(cfg['base_url'], 'https://设置端点')
        self.assertEqual(cfg['model'], '设置模型')
        self.assertEqual(cfg['key_from'], 'settings')

    def test_留空字段各自回落环境(self):
        """支持"只改模型名"这种部分覆盖。"""
        support._write(store.SETTINGS_FILE, {'api': {'model': '只改模型'}})
        cfg = llm.resolve_api_config()
        self.assertEqual(cfg['model'], '只改模型')
        self.assertEqual(cfg['base_url'], llm.ENV_BASE_URL)
        self.assertEqual(cfg['key_from'], 'env')

    def test_端点末尾斜杠被清掉(self):
        cfg = llm.resolve_api_config({'api': {'base_url': 'https://x.com/v1/'}})
        self.assertEqual(cfg['base_url'], 'https://x.com/v1')

    def test_非法max_tokens回落(self):
        cfg = llm.resolve_api_config({'api': {'max_tokens': 'abc'}})
        self.assertEqual(cfg['max_tokens'], llm.ENV_MAX_TOKENS)

    def test_缺key提示只在官方端点出现(self):
        self.assertIsNone(llm.missing_key_hint({'api_key': 'k', 'base_url': 'https://api.deepseek.com'}))
        self.assertIn('未配置', llm.missing_key_hint({'api_key': '', 'base_url': 'https://api.deepseek.com'}))
        self.assertIsNone(llm.missing_key_hint({'api_key': '', 'base_url': 'http://localhost:11434/v1'}),
                          '本地端点不该被 key 检查拦住')


if __name__ == '__main__':
    unittest.main()
