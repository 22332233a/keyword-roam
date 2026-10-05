/* ===== 漫游后自动补详情(智能档) =====
 *
 * 漫游结果一出来,就把 ⬇下级 + ↔相邻 这两组词的后台详情排队生成。
 * 你接着点任意一个,右栏直接有内容——不用等、不用手点 📖。
 *
 * 四条硬约束:
 *   1. 串行 + 间隔:并发固定 1,每条之间歇一下,绝不跟"你正在看的那个词"抢
 *   2. 隔离:只写缓存和足迹色点,绝不碰 #center-detail(否则你想看 A,右栏跳出 B)
 *   3. 静默:单条失败只留痕,不弹错、不断链;换词后旧队列继续跑完(钱已经花了)
 *   4. 不追着烂词打:同一个词连续失败到上限就不再排队(否则每漫游一次就白花一次钱),
 *      想再试就点进度文字(或手动点 📖 / 🔄重写)
 *
 * 档位(⚙设置 → 自动补详情):
 *   off   = 关
 *   smart = 只补 ⬇下级 + ↔相邻(默认)
 *   all   = 连 ⬆上级 一起补
 */

let autoQueue = [];                 // 待补的词,先进先出
let autoQueued = new Set();         // 已入队(含跑完的),用来去重
let autoRunning = false;            // 串行闸门
let autoLastWord = null;            // 上一次入队的中心词,换词就重置去重表
let autoFail = new Map();           // word -> 本页连续失败次数(队列退避;刷新即清,后端还有一份持久账)
// 进度口径:done = 真拿到详情的条数;total = 本轮排过的条数;
// failSet = 这一轮"没拿到详情"的词(含开局就知道生成不出来、直接跳过的)。
// 用集合而不是计数器:计数器和"跳过/失败"两处各自加减,会被成功分支抵消掉(踩过)。
let autoProgress = { done: 0, total: 0, failed: 0, failSet: new Set(), retrying: false };

const AUTO_DELAY_MS = 800;          // 每条之间歇一下,避免限流 + 不抢当前词
const AUTO_FAIL_LIMIT = 3;          // 与后端 store.DETAIL_FAIL_LIMIT 对齐:连续失败这么多次就不再自动打

/* 漫游结果渲染完成后由 roamdata.js 调用 */
function autoDetailFromRoam(d) {
  const mode = (setDraft && setDraft.auto_detail) || "smart";
  if (mode === "off" || !d) return;

  if (currentWord !== autoLastWord) {   // 换词 → 去重表重置(旧队列仍在跑,只是不再记它)
    autoLastWord = currentWord;
    autoQueued = new Set();
  }

  const groups = ["children", "similar"];
  if (mode === "all") groups.unshift("parents");   // all 档把上级也补上

  const picked = [];
  const blockedWords = [];   // 反复生成不出来、这次直接放弃的词(计入进度并给"重试"出口)
  for (const g of groups) {
    for (const it of d[g] || []) {
      const w = String((it && it.word) || "").trim();
      if (!w || w === currentWord || autoQueued.has(w)) continue;
      if (visited.get(w)?.feats?.includes("detail")) continue;   // 已经有详情了,不重复花钱
      autoQueued.add(w);
      if ((autoFail.get(w) || 0) >= AUTO_FAIL_LIMIT) { blockedWords.push(w); continue; }  // 已经反复失败,请求都不发
      picked.push(w);
    }
  }
  enqueueAutoDetail(picked, blockedWords.length, blockedWords);
}

/* 统一的入队出口:工具栏按钮和漫游后自动补都走这里,进度/计数口径不会走样。
   blocked 是"明知生成不出来、直接放弃"的词数(计入进度,好让"重试"入口出现)。 */
function enqueueAutoDetail(picked, blocked = 0, blockedWords = []) {
  if (blocked) {
    autoProgress.total += blocked;
    blockedWords.forEach(w => autoProgress.failSet.add(w));
  }
  if (picked && picked.length) {
    autoQueue.push(...picked);
    autoProgress.total += picked.length;
  }
  autoProgress.failed = autoProgress.failSet.size;
  if (blocked || (picked && picked.length)) {
    renderAutoProgress();
    if (picked && picked.length) pumpAutoQueue();
  }
}

/* 🔍补深挖词详情(含漫游树)由 roamdata.js 的 fillTreeDetails(deepOnly) 负责:
   它拉一次清单、报价确认、逐条走 /api/expand,并复用本文件的进度位显示。
   这里只提供"入队"这一个出口,避免两套进度口径。 */

async function pumpAutoQueue(force) {
  if (autoRunning) return;
  autoRunning = true;
  try {
    while (autoQueue.length) {
      const w = autoQueue.shift();
      if ((autoFail.get(w) || 0) >= AUTO_FAIL_LIMIT) {
        // 已知生成不出来的词:请求都不发(服务端也会拦),记进失败集,进度条不卡住
        autoProgress.failSet.add(w);
        autoProgress.failed = autoProgress.failSet.size;
        renderAutoProgress();
        continue;
      }
      await new Promise(r => setTimeout(r, AUTO_DELAY_MS));   // 让位给用户触发的请求
      let fine = false;
      try {
        await fetchDetail(w, !!force);   // 复用现成详情接口:带缓存命中、校验重掷、异常留痕
        fine = true;
      } catch (e) {
        // 静默:单条失败不弹错、不断链(abnormal.log 里已有留痕)
      }
      if (fine) {
        autoFail.delete(w);
        autoProgress.failSet.delete(w);   // 真拿到了 → 从失败集里摘掉(重试成功就该消失)
        const feats = new Set(visited.get(w)?.feats ?? []);
        feats.add("detail");
        visited.set(w, { feats: [...feats], time: Date.now() / 1000 });
        renderChips();       // 足迹 chip 色点变蓝
        refreshSeen();
        autoProgress.done++;
      } else {
        autoFail.set(w, (autoFail.get(w) || 0) + 1);   // 连续失败计数:给队列做退避
        autoProgress.failSet.add(w);
      }
      autoProgress.failed = autoProgress.failSet.size;
      renderAutoProgress();
    }
  } finally {
    autoRunning = false;
  }
}

/* "重试没能生成的词":拿一次清单,把失败的(含后端已标记跳过的)强制重跑一遍。
   修好 key / 换个模型之后,点一下就能把之前卡住的词一次性收拾掉。 */
async function retryAutoFailed() {
  if (autoRunning || autoProgress.retrying) return;
  const el = document.getElementById("tree-fill-progress");
  autoProgress.retrying = true;
  try {
    const resp = await fetch(`/api/tree-words?word=${encodeURIComponent(currentWord)}`);
    const items = (await resp.json()).items ?? [];
    const todo = items.filter(it => !it.has_detail && !it.black && !visited.get(it.word)?.feats?.includes("detail"));
    if (!todo.length) {
      if (el) el.textContent = "没有卡住的词 ✓";
      return;
    }
    if (!confirm(`${todo.length} 个词还没能生成详情(含之前反复失败的),强制重跑一遍?\n每条约 1 分钱;跑的时候漫游结果盒会一直显示进度,收起盒子不会中断。继续?`)) return;
    for (const it of todo) {
      autoFail.delete(it.word);            // 手动要求重试 → 清掉页面内的退避计数
      autoProgress.failSet.delete(it.word); // 也算作"不再失败",失败了 pump 会再加回来
    }
    autoProgress.failed = autoProgress.failSet.size;
    autoQueue.push(...todo.map(it => it.word));
    autoProgress.total += todo.length;
    renderAutoProgress();
    await pumpAutoQueue(true);
  } catch (err) {
    if (el) el.textContent = "重试失败:" + (err.message || err);
  } finally {
    autoProgress.retrying = false;
  }
}

/* 把进度写进漫游结果盒的工具栏(与"整树补详情"共用那个进度位) */
function renderAutoProgress() {
  const el = document.getElementById("tree-fill-progress");
  if (!el) return;                                    // 盒子被收起/换词重建了 → 静默继续跑
  if (typeof treeFillRunning !== "undefined" && treeFillRunning) return;  // 手动整树在跑,让位
  const { done, total, failed, retrying } = autoProgress;
  if (total === 0) return;
  el.onclick = null;
  el.title = "";
  if (retrying || done + failed < total) {
    el.textContent = `自动补详情 ${done}/${total}…`;
  } else if (failed) {
    // 失败/被跳过的词给一个明确出口,不让人对着一个失败的进度条干瞪眼
    el.textContent = `自动补详情 ${done}/${total}(失败 ${failed},点这里重试)`;
    el.title = "点一下:把这轮没能生成的词强制重跑一遍(修好 API key / 换模型后用)";
    el.onclick = retryAutoFailed;
  } else {
    el.textContent = `自动补详情 ${done}/${total} ✓`;
  }
}

