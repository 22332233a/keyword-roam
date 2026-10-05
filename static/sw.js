/* 关键词漫游器 Service Worker
 *
 * 只做一件事:让界面外壳离线可用,好让这个应用能被"安装"成桌面应用。
 * 刻意不缓存 /api/* —— 那些是动态数据,缓存了只会拿到过期结果。
 *
 * 更新策略:每次打开页面都去拉最新的 sw.js;内容一变(下面 VERSION 改了),
 * 新的 service worker 立刻接管(skipWaiting),旧缓存清掉 → 改完代码刷新就生效,
 * 不需要用户手动清缓存。
 */

const VERSION = 'v7';   // 静态资源有改动就推一格,否则缓存优先会让老前端一直不更新
const CACHE = 'roam-shell-' + VERSION;

// 界面外壳:HTML + 全部静态资源。首页 "/" 由 Flask 模板渲染,一并缓存。
const SHELL = [
  '/',
  '/static/manifest.json',
  '/static/css/style.css',
  '/static/js/state.js',
  '/static/js/common.js',
  '/static/js/sidebar.js',
  '/static/js/detail.js',
  '/static/js/roam.js',
  '/static/js/roamdata.js',
  '/static/js/chat.js',
  '/static/js/note.js',
  '/static/js/map.js',
  '/static/js/footprint.js',
  '/static/js/selection.js',
  '/static/js/autodetail.js',
  '/static/js/main.js',
  '/static/js/settings.js',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-maskable-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then(async (cache) => {
      // 逐个 add 而不是 addAll:任一资源 404 不至于让整个安装失败。
      await Promise.all(SHELL.map(async (url) => {
        try {
          await cache.add(new Request(url, { cache: 'reload' }));
        } catch (err) {
          console.warn('[sw] 外壳资源缓存失败:', url, err);
        }
      }));
      await self.skipWaiting();
    })
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
      await self.clients.claim();
    })()
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // 只接管自己这个源;外部链接(B 站/百科搜索等)交给浏览器。
  if (url.origin !== self.location.origin) return;

  // 动态接口:一律走网络,绝不缓存。离线时它自然失败,由前端自己提示。
  if (url.pathname.startsWith('/api/')) return;

  // 其余同源 GET(HTML/CSS/JS/图标):缓存优先,后台顺带刷新。
  e.respondWith(
    (async () => {
      const cache = await caches.open(CACHE);
      const cached = await cache.match(req, { ignoreSearch: true });
      const network = fetch(req)
        .then((resp) => {
          if (resp && resp.ok) cache.put(req, resp.clone());
          return resp;
        })
        .catch(() => null);
      if (cached) return cached;
      const resp = await network;
      return resp || new Response('离线且无缓存', {
        status: 503,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      });
    })()
  );
});
