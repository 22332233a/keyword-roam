/* 前端逻辑测试:用 Node 内置 vm 把**真实的** static/js/*.js 跑起来,配一套假 DOM。
 *
 * 为什么这么搭:自动补详情那套队列/退避/进度逻辑全在前端,而且踩过两次坑
 * (挂错位置、重入竞态)。这些用 pytest 测不到,起真浏览器又太重。
 *
 * 跑法:node tests/js/run_frontend_tests.mjs
 * 退出码:0 = 全过,1 = 有失败
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const read = f => fs.readFileSync(path.join(ROOT, 'static', 'js', f), 'utf8');

const autodetail = read('autodetail.js');
const state = read('state.js');

let passed = 0;
const failures = [];

function ok(name, cond, extra = '') {
  if (cond) { passed += 1; console.log(`  ✓ ${name}`); }
  else { failures.push(name + (extra ? '  ' + extra : '')); console.log(`  ✗ ${name}  ${extra}`); }
}

function eq(name, got, want) {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  ok(name, g === w, g === w ? '' : `得到 ${g},期望 ${w}`);
}

/* ---------- 假 DOM:只实现被测代码真正用到的那几个 API ---------- */
function makeEnv({ progressEl = { textContent: '', title: '', onclick: null } } = {}) {
  const els = new Map([['tree-fill-progress', progressEl]]);
  const document = {
    getElementById: id => els.get(id) ?? null,
    querySelectorAll: () => [],
    querySelector: () => null,
  };
  const context = vm.createContext({
    document,
    console,
    setTimeout,
    clearTimeout,
    // ---- 被测代码依赖的应用状态/函数(statements 里声明) ----
    setDraft: { auto_detail: 'smart' },
    currentWord: '中心词',
    visited: new Map(),
    autoFail: new Map(),
    fetchDetail: async () => { throw new Error('默认桩:应被测试覆盖'); },
    renderChips: () => {},
    refreshSeen: () => {},
    confirm: () => true,
  });
  vm.runInContext(state, context, { filename: 'state.js' });
  vm.runInContext(autodetail, context, { filename: 'autodetail.js' });
  // 每条用例都从干净状态起步:不重置 autoLastWord 的话,上一条用例攒下的 autoQueued
  // 会让这一条的词被当成"已经排过"而跳过 —— 结果是测试自己在骗自己。
  vm.runInContext('autoLastWord = null; autoQueued = new Set(); autoQueue.length = 0;', context);
  return { context, progressEl, els, document };
}

/* 等队列跑空。注意给够时间:AUTO_DELAY_MS=800,每条之间都要等,默认 2s 会提前返回。 */
async function drain(env, ms = 20000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (stateOf(env, 'autoRunning') === false && stateOf(env, 'autoQueue.length') === 0) return;
    await new Promise(r => setTimeout(r, 10));
  }
  throw new Error('drain 超时:队列没跑完');
}

/* 替换 fetchDetail 为记录桩;只记录不执行(想断言"排了哪些词"时用,不触发队列消费) */
function spy(env) {
  env.context.__impl = () => new Promise(() => {});
  vm.runInContext(`
    var __calls = [];
    fetchDetail = async function (w, force) {
      __calls.push([w, !!force]);
      return globalThis.__impl(w, force);
    };
    pumpAutoQueue = async function () {};   // 拦住,让队列停在原地便于断言
  `, env.context, { filename: 'spy.js' });
}

/* 把 fetchDetail 换成记账桩。
   注意:断言不能读 autoQueue —— pumpAutoQueue() 会**同步** shift() 掉第一个词再去 await,
   所以队列随时处于"正在被消费"的中间态。要看"排了哪些词",统一看这里的调用记录。 */
let calls = [];
function stub(env, impl) {
  calls = [];
  env.context.__impl = impl || (() => { throw new Error('未提供实现'); });
  vm.runInContext(`
    var __calls = [];
    fetchDetail = async function (w, force) {
      __calls.push([w, !!force]);
      return globalThis.__impl(w, force);
    };
  `, env.context, { filename: 'stub.js' });
}
const fetchLog = env => JSON.parse(stateOf(env, 'JSON.stringify(__calls)')).map(c => c[0]).sort();

const stateOf = (env, expr) => vm.runInContext(expr, env.context);
const run = async (env, body) => vm.runInContext(body, env.context);

/* ================= 测试 ================= */
console.log('\n=== autodetail.js:入队判据 ===');

{
  const env = makeEnv();
  spy(env);   // 拦住 pump,直接看"排了哪些词"
  const d = {
    word: '中心词',
    parents: [{ word: '上级A' }, { word: '上级B' }],
    children: [{ word: '下级A' }, { word: '下级B' }],
    similar: [{ word: '相邻A' }],
  };
  vm.runInContext('currentWord = "中心词"', env.context);
  await run(env, `autoDetailFromRoam(${JSON.stringify(d)})`);
  eq('smart 档只排下级+相邻,不排上级', stateOf(env, 'autoQueue.slice()'), ['下级A', '下级B', '相邻A']);
}

{
  const env = makeEnv();
  spy(env);
  vm.runInContext('currentWord = "中心词"; setDraft.auto_detail = "all"', env.context);
  const d = { parents: [{ word: '上级A' }], children: [{ word: '下级A' }], similar: [{ word: '相邻A' }] };
  await run(env, `autoDetailFromRoam(${JSON.stringify(d)})`);
  eq('all 档把上级也排进去', stateOf(env, 'autoQueue.slice()'), ['上级A', '下级A', '相邻A']);
}

{
  const env = makeEnv();
  stub(env);
  vm.runInContext('setDraft.auto_detail = "off"', env.context);
  await run(env, 'autoDetailFromRoam({children:[{word:"下级A"}],similar:[]})');
  await drain(env);
  eq('off 档一个都不排', fetchLog(env), []);
}

{
  const env = makeEnv();
  stub(env);
  vm.runInContext('visited.set("下级A", {feats:["detail"]})', env.context);
  await run(env, 'autoDetailFromRoam({children:[{word:"下级A"},{word:"下级B"}],similar:[]})');
  await drain(env);
  eq('已有详情的词不再花钱', fetchLog(env), ['下级B']);
}

{
  const env = makeEnv();
  stub(env);
  const d = JSON.stringify({ children: [{ word: '下级A' }, { word: '下级B' }], similar: [] });
  await run(env, `autoDetailFromRoam(${d})`);
  await run(env, `autoDetailFromRoam(${d})`);
  await drain(env);
  eq('同一次漫游重复渲染不会重复请求', fetchLog(env), ['下级A', '下级B']);
}

{
  const env = makeEnv();
  stub(env);
  await run(env, 'autoDetailFromRoam({children:[{word:"下级A"}],similar:[]})');
  await drain(env);
  vm.runInContext('currentWord = "另一个词"', env.context);
  await run(env, 'autoDetailFromRoam({children:[{word:"下级A"}],similar:[]})');
  await drain(env);
  eq('换词后同一个词可以再排一次', fetchLog(env), ['下级A', '下级A']);
}

{
  const env = makeEnv();
  stub(env);
  await run(env, 'autoDetailFromRoam(null)');
  await drain(env);
  eq('没有数据不炸也不排队', fetchLog(env), []);
}

console.log('\n=== autodetail.js:失败退避(不追着烂词打) ===');

{
  const env = makeEnv();
  stub(env);
  vm.runInContext('autoFail.set("烂词", 3); autoQueued.add("烂词"); autoQueue.push("烂词")', env.context);
  await run(env, 'pumpAutoQueue()');
  await drain(env);
  eq('已达上限的词一条请求都不发', fetchLog(env), []);
  eq('失败次数不再增长', stateOf(env, 'autoFail.get("烂词")'), 3);
  eq('但计入进度(好让"重试"入口出现)', stateOf(env, 'autoProgress.failed'), 1);
}

{
  const env = makeEnv();
  stub(env, () => { throw new Error('失败'); });
  await run(env, 'autoQueued.add("新烂词"); autoQueue.push("新烂词"); pumpAutoQueue()');
  await drain(env);
  eq('失败一次记一次', stateOf(env, 'autoFail.get("新烂词")'), 1);
  eq('失败计入进度', stateOf(env, 'autoProgress.failed'), 1);
}

{
  const env = makeEnv();
  stub(env, () => ({ detail: 'x' }));
  vm.runInContext('autoFail.set("好转词", 2)', env.context);
  await run(env, 'autoQueued.add("好转词"); autoQueue.push("好转词"); pumpAutoQueue()');
  await drain(env);
  ok('成功会清掉退避计数', stateOf(env, 'autoFail.has("好转词")') === false);
  eq('成功计入 done', stateOf(env, 'autoProgress.done'), 1);
  ok('成功后写入足迹', stateOf(env, 'visited.get("好转词").feats.includes("detail")') === true);
  eq('成功时不把失败数算进去', stateOf(env, 'autoProgress.failed'), 0);
}

{
  const env = makeEnv();
  const order = [];
  stub(env, w => { order.push(w); return { detail: 'x' }; });
  await run(env, 'autoQueue.push("一","二","三"); pumpAutoQueue()');
  await drain(env);
  eq('串行按顺序跑完', order, ['一', '二', '三']);
  eq('跑完队列清空', stateOf(env, 'autoQueue.length'), 0);
}

{
  const env = makeEnv();
  stub(env);
  await run(env, 'autoQueue.push("a","b"); pumpAutoQueue(); pumpAutoQueue()');   // 第二次应被闸门挡住
  await drain(env);
  eq('并发闸门:同时两次 pump 不会重复跑', fetchLog(env), ['a', 'b']);
}

console.log('\n=== autodetail.js:进度显示 ===');

{
  const env = makeEnv();
  stub(env);
  await run(env, 'autoProgress.total = 3; autoProgress.done = 2; autoProgress.failed = 1; renderAutoProgress()');
  ok('有失败时给出重试入口', String(env.progressEl.textContent).includes('重试'), env.progressEl.textContent);
  ok('重试入口是函数', typeof env.progressEl.onclick === 'function');
}

{
  const env = makeEnv();
  stub(env);
  await run(env, 'autoProgress.total = 2; autoProgress.done = 2; autoProgress.failed = 0; renderAutoProgress()');
  ok('全成功显示 ✓', String(env.progressEl.textContent).includes('✓'), env.progressEl.textContent);
  ok('全成功时不挂重试', env.progressEl.onclick === null);
}

{
  const env = makeEnv();
  stub(env);
  await run(env, 'autoProgress.total = 5; autoProgress.done = 2; renderAutoProgress()');
  ok('跑动中显示进度', String(env.progressEl.textContent).includes('2/5'), env.progressEl.textContent);
}

{
  const env = makeEnv({ progressEl: null });
  stub(env);
  let threw = false;
  try { await run(env, 'autoProgress.total = 1; renderAutoProgress()'); } catch { threw = true; }
  ok('盒子被收起(元素没了)也不许抛异常', !threw);
}

console.log('\n=== autodetail.js:统一入队出口 ===');
{
  const env = makeEnv();
  stub(env, () => ({ detail: 'x' }));          // 让 fetch 成功,否则失败计数会把断言搅乱
  await run(env, 'enqueueAutoDetail(["a","b"], 2, ["挡下一","挡下二"])');
  await drain(env);
  eq('被挡下的词计入 total', stateOf(env, 'autoProgress.total'), 4);
  eq('被挡下的词计入 failed', stateOf(env, 'autoProgress.failed'), 2);
  eq('要跑的词都进过队列', fetchLog(env), ['a', 'b']);
}

{
  const env = makeEnv();
  stub(env);
  await run(env, 'enqueueAutoDetail([], 2, ["挡下一","挡下二"])');
  eq('只有被挡下的词时,进度也照样出现(failed 不被清零)', stateOf(env, 'autoProgress.failed'), 2);
  eq('total 只算被挡下的', stateOf(env, 'autoProgress.total'), 2);
}

console.log('\n=== footprint.js:时间分桶 ===');
{
  /* timeBucket 是纯函数,footprint.js 顶层又不碰 DOM,裸上下文就能跑 */
  const ctx = vm.createContext({ document: { getElementById: () => null } });
  vm.runInContext(read('footprint.js'), ctx, { filename: 'footprint.js' });
  const at = expr => vm.runInContext(expr, ctx);
  const DAY = 86400000;
  const midnight = new Date(); midnight.setHours(0, 0, 0, 0);
  const startMs = midnight.getTime();
  eq('今天零点整 → 今天', at(`timeBucket(${startMs})`), '今天');
  eq('两小时前 → 今天', at(`timeBucket(${Date.now() - 2 * 3600 * 1000})`), '今天');
  eq('昨天半夜 → 最近三天', at(`timeBucket(${startMs - 0.5 * DAY})`), '最近三天');
  eq('四天前 → 一周内', at(`timeBucket(${startMs - 4 * DAY})`), '一周内');
  eq('一个月前 → 更早', at(`timeBucket(${startMs - 30 * DAY})`), '更早');
  eq('无时间戳(0) → 更早', at('timeBucket(0)'), '更早');
}

console.log(`\n===== 前端测试:通过 ${passed} / 失败 ${failures.length} =====`);
if (failures.length) {
  console.log('失败项:');
  failures.forEach(f => console.log('  - ' + f));
  process.exit(1);
}
process.exit(0);
