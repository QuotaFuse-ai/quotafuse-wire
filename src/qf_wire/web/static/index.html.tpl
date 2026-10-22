<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>QuotaFuse Wire · 资讯看板</title>
<style>
  :root {
    color-scheme: dark;
    --bg: #0b1020;
    --panel: #141b2f;
    --panel-2: #1b2440;
    --text: #e6ecff;
    --muted: #8b97b8;
    --line: #263252;
    --accent: #22d3ee;
    --warn: #f59e0b;
    --danger: #f87171;
    --ok: #34d399;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
    background: radial-gradient(1200px 600px at 20% -10%, #1b2748 0, var(--bg) 55%);
    color: var(--text);
    min-height: 100vh;
  }
  header {
    position: sticky; top: 0; z-index: 5;
    display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
    padding: 14px 22px;
    background: rgba(11, 16, 32, .86);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--line);
  }
  header h1 { font-size: 17px; margin: 0; letter-spacing: .3px; }
  header .brand-dot {
    display: inline-block; width: 9px; height: 9px; border-radius: 50%;
    background: var(--accent); margin-right: 9px;
    box-shadow: 0 0 12px var(--accent);
  }
  header .meta { color: var(--muted); font-size: 12px; }
  header .spacer { flex: 1; }
  input[type="search"] {
    width: min(320px, 60vw);
    padding: 8px 12px; border-radius: 9px;
    border: 1px solid var(--line); background: var(--panel);
    color: var(--text); outline: none;
  }
  input[type="search"]:focus { border-color: var(--accent); }
  button {
    padding: 8px 13px; border-radius: 9px; cursor: pointer;
    border: 1px solid var(--line); background: var(--panel-2); color: var(--text);
  }
  button:hover { border-color: var(--accent); }
  main { max-width: 1120px; margin: 0 auto; padding: 20px 22px 60px; }
  #notices { display: grid; gap: 8px; margin-bottom: 16px; }
  .notice {
    padding: 10px 14px; border-radius: 10px;
    border: 1px solid rgba(248, 113, 113, .35);
    background: rgba(248, 113, 113, .08);
    color: #fecaca; font-size: 13px;
  }
  .tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }
  .tab {
    border: 1px solid var(--line); background: var(--panel);
    color: var(--muted); padding: 7px 13px; border-radius: 999px;
    font-size: 13px; cursor: pointer;
  }
  .tab.active { color: #071018; background: var(--accent); border-color: var(--accent); font-weight: 600; }
  .panel {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 14px; padding: 16px 18px; margin-bottom: 16px;
  }
  .panel h2 { margin: 0 0 8px; font-size: 14px; color: var(--muted); font-weight: 600; letter-spacing: .4px; }
  #digest { white-space: pre-wrap; line-height: 1.7; font-size: 14px; }
  #points { margin: 10px 0 0; padding-left: 20px; color: #c9d4f2; font-size: 13.5px; line-height: 1.65; }
  .items { display: grid; gap: 12px; }
  .item {
    background: var(--panel); border: 1px solid var(--line); border-radius: 13px;
    padding: 14px 16px; transition: border-color .15s ease, transform .15s ease;
  }
  .item:hover { border-color: var(--accent); transform: translateY(-1px); }
  .item .head { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  .item h3 { margin: 0; font-size: 15.5px; line-height: 1.45; flex: 1; min-width: 240px; }
  .item h3 a { color: var(--text); text-decoration: none; }
  .item h3 a:hover { color: var(--accent); }
  .item .orig { color: var(--muted); font-size: 12px; margin-top: 4px; }
  .item .summary { color: #b7c3e2; font-size: 13.5px; line-height: 1.65; margin-top: 8px; }
  .badges { display: flex; gap: 6px; flex-wrap: wrap; }
  .badge {
    font-size: 11px; color: var(--muted); border: 1px solid var(--line);
    border-radius: 999px; padding: 2px 8px; white-space: nowrap;
  }
  .badge.high { color: var(--ok); border-color: rgba(52, 211, 153, .4); }
  .badge.low { color: var(--warn); border-color: rgba(245, 158, 11, .4); }
  .empty { color: var(--muted); text-align: center; padding: 48px 0; font-size: 14px; }
  details.source-panel summary { cursor: pointer; color: var(--muted); font-size: 13px; }
  table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12.5px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); }
  th { color: var(--muted); font-weight: 600; }
  td.status-ok { color: var(--ok); }
  td.status-degraded { color: var(--warn); }
  td.status-unavailable { color: var(--danger); }
  @media (max-width: 560px) {
    header h1 { font-size: 15px; }
    main { padding: 14px 12px 48px; }
  }
</style>
</head>
<body>
<header>
  <h1><span class="brand-dot"></span>QuotaFuse Wire</h1>
  <span class="meta" id="generated">加载中…</span>
  <span class="spacer"></span>
  <input id="search" type="search" placeholder="搜索标题 / 摘要 / 信源" autocomplete="off" />
  <button id="refresh" type="button">刷新</button>
</header>
<main>
  <div id="notices"></div>
  <div class="tabs" id="tabs"></div>
  <section class="panel" id="digest-panel" hidden>
    <h2>今日提炼</h2>
    <div id="digest"></div>
    <ul id="points"></ul>
  </section>
  <div class="items" id="items"><div class="empty">加载中…</div></div>
  <details class="panel source-panel" id="source-panel" hidden>
    <summary>信源状态</summary>
    <table>
      <thead><tr><th>信源</th><th>赛道</th><th>状态</th><th>条目</th><th>尝试</th><th>错误</th></tr></thead>
      <tbody id="source-body"></tbody>
    </table>
  </details>
</main>
<script>
(function () {
  "use strict";

  var state = { key: null, query: "" };
  var data = { industries: [] };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function currentIndustry() {
    var list = data.industries || [];
    if (!list.length) return null;
    for (var i = 0; i < list.length; i += 1) {
      if (list[i].key === state.key) return list[i];
    }
    state.key = list[0].key;
    return list[0];
  }

  function matches(item) {
    if (!state.query) return true;
    var q = state.query.toLowerCase();
    var fields = [item.title, item.zh, item.summary, item.source];
    for (var i = 0; i < fields.length; i += 1) {
      if (String(fields[i] || "").toLowerCase().indexOf(q) !== -1) return true;
    }
    return false;
  }

  function renderTabs() {
    var tabs = document.getElementById("tabs");
    tabs.textContent = "";
    (data.industries || []).forEach(function (industry) {
      var count = (industry.items || []).length;
      var tab = el("button", "tab" + (industry.key === state.key ? " active" : ""), industry.name + " · " + count);
      tab.type = "button";
      tab.addEventListener("click", function () {
        state.key = industry.key;
        render();
      });
      tabs.appendChild(tab);
    });
  }

  function renderDigest(industry) {
    var panel = document.getElementById("digest-panel");
    var digest = document.getElementById("digest");
    var points = document.getElementById("points");
    points.textContent = "";
    var summary = (industry && industry.summary) || "";
    var keyPoints = (industry && industry.key_points) || [];
    if (!summary && !keyPoints.length) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    digest.textContent = summary;
    keyPoints.forEach(function (point) {
      points.appendChild(el("li", "", point.text || ""));
    });
  }

  function renderItems(industry) {
    var wrap = document.getElementById("items");
    wrap.textContent = "";
    var items = ((industry && industry.items) || []).filter(matches);
    if (!items.length) {
      wrap.appendChild(el("div", "empty", state.query ? "没有匹配的资讯" : "该赛道今日暂无资讯"));
      return;
    }
    items.forEach(function (item) {
      var card = el("article", "item");
      var head = el("div", "head");
      var title = el("h3");
      var link = el("a", null, item.zh || item.title || "(无标题)");
      link.href = item.url || "#";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      title.appendChild(link);
      head.appendChild(title);

      var badges = el("div", "badges");
      if (item.time) badges.appendChild(el("span", "badge", item.time));
      if (item.source) badges.appendChild(el("span", "badge", item.source));
      var confidence = item.confidence || "medium";
      badges.appendChild(el("span", "badge " + confidence, "置信 " + confidence));
      if (item.source_count > 1) badges.appendChild(el("span", "badge high", item.source_count + " 源"));
      head.appendChild(badges);
      card.appendChild(head);

      if (item.zh && item.title && item.zh !== item.title) {
        card.appendChild(el("div", "orig", item.title));
      }
      if (item.summary) card.appendChild(el("div", "summary", item.summary));
      if (item.event_id) {
        var ev = el("div", "badges");
        ev.appendChild(el("span", "badge", "event " + item.event_id));
        card.appendChild(ev);
      }
      wrap.appendChild(card);
    });
  }

  function renderNotices() {
    var wrap = document.getElementById("notices");
    wrap.textContent = "";
    (data.sourceNotice || []).forEach(function (text) {
      wrap.appendChild(el("div", "notice", text));
    });
  }

  function renderSources() {
    var panel = document.getElementById("source-panel");
    var body = document.getElementById("source-body");
    var rows = data.sourceStatus || [];
    body.textContent = "";
    if (!rows.length) { panel.hidden = true; return; }
    panel.hidden = false;
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      tr.appendChild(el("td", "", row.name || row.id));
      tr.appendChild(el("td", "", row.topic || ""));
      tr.appendChild(el("td", "status-" + (row.status || ""), row.status || ""));
      tr.appendChild(el("td", "", row.itemCount === undefined ? "" : row.itemCount));
      tr.appendChild(el("td", "", row.attempts === undefined ? "" : row.attempts));
      tr.appendChild(el("td", "", row.error || ""));
      body.appendChild(tr);
    });
  }

  function render() {
    var industry = currentIndustry();
    document.getElementById("generated").textContent = data.generatedAt
      ? "生成于 " + data.generatedAt
      : "暂无数据";
    renderNotices();
    renderTabs();
    renderDigest(industry);
    renderItems(industry);
    renderSources();
  }

  function load() {
    var previous = document.getElementById("wire-data");
    if (previous) previous.remove();
    var script = document.createElement("script");
    script.id = "wire-data";
    script.src = "/data.js?t=" + Date.now();
    script.onload = function () {
      data = window.DATA || { industries: [] };
      if (!state.key && data.industries && data.industries.length) {
        state.key = data.industries[0].key;
      }
      render();
    };
    script.onerror = function () {
      var wrap = document.getElementById("items");
      wrap.textContent = "";
      wrap.appendChild(el("div", "empty", "无法加载 data.js，请先运行 qfw run"));
    };
    document.body.appendChild(script);
  }

  document.getElementById("search").addEventListener("input", function (event) {
    state.query = event.target.value.trim();
    render();
  });
  document.getElementById("refresh").addEventListener("click", load);
  setInterval(load, 5 * 60 * 1000);
  load();
})();
</script>
</body>
</html>
