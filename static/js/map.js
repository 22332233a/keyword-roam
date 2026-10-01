/* ===== 🗺 足迹地图:力导向词图 + 两词最短路径 =====
       缓存词做物理(斥力+弹簧+向心),没走过的邻居挂在锚点周围不参与模拟(量大,省算力);
       拖词/拖背景/滚轮缩放;🔗路径模式:点起点再点终点,BFS 高亮最短链。 */
    let mapOpen = false, mapRaf = 0, byWord = new Map(), mapAdj = new Map();
    let mapNodes = [], mapEdges = [], mapFrontier = [];
    let cam = { x: 0, y: 0, z: 1 };
    let mapDrag = null, showFrontier = false, mapHover = null;
    let pathMode = false, pathA = null, pathWords = null;

    async function toggleMap() {
      const v = document.getElementById("map-view");
      if (!v.hidden) { closeMap(); return; }
      v.hidden = false;
      resizeMap();
      try {
        const resp = await fetch("/api/graph");
        if (!resp.ok) throw new Error((await resp.json()).error || resp.statusText);
        buildMap(await resp.json());
        for (let i = 0; i < 150; i++) stepSim();   // 开图前先静算几步,布局落座再亮相
        fitMap();
        mapOpen = true;
        startMap();
      } catch (err) {
        closeMap();
        alert("地图加载失败:" + (err.message || err));
      }
    }

    function closeMap() {
      document.getElementById("map-view").hidden = true;
      mapOpen = false;
      cancelAnimationFrame(mapRaf);
    }

    function buildMap(body) {
      const old = new Map(mapNodes.map(n => [n.word, n]));
      mapNodes = body.nodes.map(n => {
        const o = old.get(n.word);
        const a = Math.random() * Math.PI * 2, r = 300 * Math.sqrt(Math.random());
        return { word: n.word, feats: n.feats ?? [], deg: 0, fixed: 0,
                 x: o ? o.x : Math.cos(a) * r, y: o ? o.y : Math.sin(a) * r, vx: 0, vy: 0, r: 5 };
      });
      byWord = new Map(mapNodes.map(n => [n.word, n]));
      mapEdges = (body.edges || []).filter(e => byWord.has(e.a) && byWord.has(e.b));
      for (const e of mapEdges) { byWord.get(e.a).deg++; byWord.get(e.b).deg++; }
      mapAdj = new Map();
      for (const e of mapEdges) {
        if (!mapAdj.has(e.a)) mapAdj.set(e.a, new Set());
        if (!mapAdj.has(e.b)) mapAdj.set(e.b, new Set());
        mapAdj.get(e.a).add(e.b); mapAdj.get(e.b).add(e.a);
      }
      let slot = 0;
      mapFrontier = (body.frontier || []).filter(f => byWord.has(f.anchor))
        .map(f => ({ word: f.word, node: byWord.get(f.anchor), slot: slot++ }));
      pathA = null; pathWords = null;
      updateMapStat();
    }

    function nodeColor(n) {
      const f = n.feats ?? [];
      if (f.includes("deep")) return "#b48aff";    // 紫=深挖过
      if (f.includes("detail")) return "#5b83d6";  // 蓝=读过详情
      return "#5da97a";                            // 绿=只漫游过
    }

    function frontierXY(f) {
      const ang = f.slot * 2.399963, r = 26 + (f.slot % 5) * 11;   // 黄金角扇形摊开
      return { x: f.node.x + Math.cos(ang) * r, y: f.node.y + Math.sin(ang) * r };
    }

    function stepSim() {
      const ns = mapNodes, n = ns.length;
      for (let i = 0; i < n; i++) {
        const a = ns[i];
        for (let j = i + 1; j < n; j++) {
          const b = ns[j];
          const dx = b.x - a.x, dy = b.y - a.y;
          const d2 = Math.max(dx * dx + dy * dy, 1);
          const d = Math.sqrt(d2), f = 2400 / d2;
          const fx = dx / d * f, fy = dy / d * f;
          a.vx -= fx; a.vy -= fy; b.vx += fx; b.vy += fy;
        }
      }
      for (const e of mapEdges) {
        const a = byWord.get(e.a), b = byWord.get(e.b);
        const dx = b.x - a.x, dy = b.y - a.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = (d - 70) * 0.03;
        const fx = dx / d * f, fy = dy / d * f;
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
      }
      for (const p of ns) {
        p.vx = (p.vx - p.x * 0.004) * 0.86;
        p.vy = (p.vy - p.y * 0.004) * 0.86;
        if (p.fixed) { p.vx = p.vy = 0; continue; }
        const sp = Math.hypot(p.vx, p.vy);
        if (sp > 10) { p.vx *= 10 / sp; p.vy *= 10 / sp; }
        p.x += p.vx; p.y += p.vy;
      }
    }

    function drawMap() {
      const cv = document.getElementById("map-canvas");
      const ctx = cv.getContext("2d");
      const w = cv.clientWidth, h = cv.clientHeight;
      ctx.setTransform(devicePixelRatio || 1, 0, 0, devicePixelRatio || 1, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.translate(w / 2, h / 2);
      ctx.scale(cam.z, cam.z);
      ctx.translate(-cam.x, -cam.y);

      // 悬停聚焦:非邻居一律淡出,迷宫变局部图
      const nb = mapHover ? mapAdj.get(mapHover) : null;
      const keep = nb ? new Set([mapHover, ...nb]) : null;

      ctx.lineWidth = 1 / cam.z;
      for (const e of mapEdges) {
        const a = byWord.get(e.a), b = byWord.get(e.b);
        ctx.strokeStyle = keep
          ? (e.a === mapHover || e.b === mapHover ? "rgba(190,200,225,0.85)" : "rgba(120,130,150,0.05)")
          : "rgba(120,130,150,0.28)";
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      }
      if (showFrontier) {
        ctx.lineWidth = 1 / cam.z;
        for (const f of mapFrontier) {
          const p = frontierXY(f);
          const on = keep ? keep.has(f.word) || f.node.word === mapHover : false;
          ctx.strokeStyle = on ? "rgba(190,200,225,0.6)" : keep ? "rgba(120,130,150,0.04)" : "rgba(120,130,150,0.13)";
          ctx.beginPath(); ctx.moveTo(f.node.x, f.node.y); ctx.lineTo(p.x, p.y); ctx.stroke();
          ctx.globalAlpha = keep && !on ? 0.12 : 1;
          ctx.beginPath(); ctx.arc(p.x, p.y, 3, 0, 7);
          ctx.fillStyle = "#1c1f28"; ctx.fill();
          ctx.strokeStyle = "#4a5060"; ctx.stroke();
          ctx.globalAlpha = 1;
          if (cam.z > 1.6 || on) {
            ctx.fillStyle = on ? "#c8cede" : "#6a7180";
            ctx.font = `${10 / cam.z}px sans-serif`;
            ctx.fillText(f.word, p.x + 4, p.y + 3);
          }
        }
      }
      if (pathWords && pathWords.length > 1) {
        ctx.strokeStyle = "#ffb454";
        ctx.lineWidth = 2.5 / cam.z;
        for (let i = 0; i + 1 < pathWords.length; i++) {
          const a = byWord.get(pathWords[i]), b = byWord.get(pathWords[i + 1]);
          if (!a || !b) continue;
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        }
      }
      for (const p of mapNodes) {
        p.r = 4 + Math.min(p.deg, 24) * 0.5;
        const inPath = pathWords?.includes(p.word);
        const on = keep ? keep.has(p.word) : true;
        ctx.globalAlpha = on ? 1 : 0.13;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 7);
        ctx.fillStyle = nodeColor(p);
        ctx.fill();
        if (inPath || p.word === pathA) {
          ctx.strokeStyle = "#ffb454"; ctx.lineWidth = 2 / cam.z; ctx.stroke();
        }
        const show = on && !keep ? cam.z > 0.55 || inPath || p.word === pathA || p.deg >= 8
                   : keep && (p.word === mapHover || nb?.has(p.word));
        if (show || inPath || p.word === pathA) {
          ctx.fillStyle = inPath || p.word === pathA || p.word === mapHover ? "#ffb454" : "#a8b0c0";
          ctx.font = `${(inPath || p.word === mapHover ? "bold " : "") + 11 / cam.z}px sans-serif`;
          ctx.fillText(p.word, p.x + p.r + 2, p.y + 3);
        }
        ctx.globalAlpha = 1;
      }
      ctx.setTransform(1, 0, 0, 1, 0, 0);
    }

    function startMap() {
      cancelAnimationFrame(mapRaf);
      const loop = () => {
        if (!mapOpen) return;
        stepSim();
        drawMap();
        mapRaf = requestAnimationFrame(loop);
      };
      loop();
    }

    function resizeMap() {
      const cv = document.getElementById("map-canvas");
      const dpr = window.devicePixelRatio || 1;
      cv.width = cv.clientWidth * dpr;
      cv.height = cv.clientHeight * dpr;
      if (mapOpen) drawMap();
    }
    window.addEventListener("resize", () => { if (mapOpen) resizeMap(); });

    function fitMap() {
      if (!mapNodes.length) return;
      let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      for (const p of mapNodes) {
        x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y);
        x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y);
      }
      const cv = document.getElementById("map-canvas");
      cam.x = (x0 + x1) / 2; cam.y = (y0 + y1) / 2;
      cam.z = Math.max(0.15, Math.min(2.5,
        Math.min(cv.clientWidth / (x1 - x0 + 180), cv.clientHeight / (y1 - y0 + 180))));
    }

    function mapXY(ev) {
      const rect = ev.target.getBoundingClientRect();
      return { x: (ev.clientX - rect.left - rect.width / 2) / cam.z + cam.x,
               y: (ev.clientY - rect.top - rect.height / 2) / cam.z + cam.y };
    }

    function pickNode(wx, wy) {
      let best = null, bd = 1e9;
      for (const p of mapNodes) {
        const d = Math.hypot(p.x - wx, p.y - wy);
        if (d < p.r + 5 / cam.z && d < bd) { best = p; bd = d; }
      }
      return best;
    }

    let lastMouse = null;
    function mapDown(ev) {
      const p = mapXY(ev);
      const n = pickNode(p.x, p.y);
      if (n) n.fixed++;
      mapDrag = { sx: ev.clientX, sy: ev.clientY, node: n, moved: false };
      lastMouse = { x: ev.clientX, y: ev.clientY };
    }
    function mapMove(ev) {
      if (!mapDrag) {
        const p = mapXY(ev);
        mapHover = pickNode(p.x, p.y)?.word || null;
        return;
      }
      const dx = ev.clientX - mapDrag.sx, dy = ev.clientY - mapDrag.sy;
      if (Math.hypot(dx, dy) > 3) mapDrag.moved = true;
      if (!mapDrag.moved) return;
      if (mapDrag.node) {
        const p = mapXY(ev);
        mapDrag.node.x = p.x; mapDrag.node.y = p.y;
      } else {
        cam.x -= (ev.clientX - lastMouse.x) / cam.z;
        cam.y -= (ev.clientY - lastMouse.y) / cam.z;
      }
      lastMouse = { x: ev.clientX, y: ev.clientY };
    }
    function mapUp(ev) {
      if (!mapDrag) return;
      if (mapDrag.node) mapDrag.node.fixed = Math.max(0, mapDrag.node.fixed - 1);
      if (!mapDrag.moved) {
        const p = mapXY(ev);
        mapClick(p.x, p.y);
      }
      mapDrag = null;
    }
    function mapWheel(ev) {
      ev.preventDefault();
      const rect = ev.target.getBoundingClientRect();
      const sx = ev.clientX - rect.left - rect.width / 2, sy = ev.clientY - rect.top - rect.height / 2;
      const wx = sx / cam.z + cam.x, wy = sy / cam.z + cam.y;
      cam.z = Math.min(8, Math.max(0.12, cam.z * (ev.deltaY < 0 ? 1.15 : 1 / 1.15)));
      cam.x = wx - sx / cam.z; cam.y = wy - sy / cam.z;
    }

    function mapClick(wx, wy) {
      const n = pickNode(wx, wy);
      if (!n) return;
      if (pathMode) {
        if (!pathA || pathWords) {
          pathA = n.word; pathWords = null;
          mapPathInfo(`起点:「${n.word}」,再点终点`);
        } else if (n.word === pathA) {
          pathA = null;
          mapPathInfo("取消了起点");
        } else {
          pathWords = bfsPath(pathA, n.word);
          mapPathInfo(pathWords
            ? `最短 ${pathWords.length - 1} 步:${pathWords.join(" → ")}`
            : `「${pathA}」和「${n.word}」不连通`);
        }
        return;
      }
      closeMap();
      goWord(n.word);
    }

    function armPath() {
      pathMode = !pathMode;
      pathA = null; pathWords = null;
      document.getElementById("map-path-btn").classList.toggle("active", pathMode);
      mapPathInfo(pathMode ? "路径模式:先点起点,再点终点(Esc 退出)" : "");
    }

    function toggleFrontier() {
      showFrontier = document.getElementById("map-frontier").checked;
      pathA = null; pathWords = null;
      mapPathInfo(showFrontier ? `邻居已展开(${mapFrontier.length} 个),路径可穿过没走过的词` : "");
      updateMapStat();
    }

    function bfsPath(a, b) {
      const adj = new Map();
      const link = (x, y) => { const l = adj.get(x) || []; l.push(y); adj.set(x, l); };
      for (const e of mapEdges) { link(e.a, e.b); link(e.b, e.a); }
      if (showFrontier) for (const f of mapFrontier) { link(f.node.word, f.word); link(f.word, f.node.word); }
      const prev = new Map([[a, null]]);
      const q = [a];
      while (q.length) {
        const x = q.shift();
        if (x === b) break;
        for (const y of adj.get(x) || []) if (!prev.has(y)) { prev.set(y, x); q.push(y); }
      }
      if (!prev.has(b)) return null;
      const path = [];
      for (let x = b; x != null; x = prev.get(x)) path.unshift(x);
      return path;
    }

    function mapPathInfo(t) { document.getElementById("map-path-info").textContent = t; }
    function updateMapStat() {
      document.getElementById("map-stat").textContent =
        `${mapNodes.length} 词 · ${mapEdges.length} 条关系` +
        (showFrontier ? ` · ${mapFrontier.length} 个没走过` : "");
    }
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && !document.getElementById("map-view").hidden) closeMap();
    });
    {
      const cv = document.getElementById("map-canvas");
      cv.addEventListener("mousedown", mapDown);
      cv.addEventListener("wheel", mapWheel, { passive: false });
      window.addEventListener("mousemove", mapMove);
      window.addEventListener("mouseup", mapUp);
    }

    