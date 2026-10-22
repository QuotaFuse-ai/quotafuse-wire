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
    position: sticky; top: 0; z-index: 20;
    display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
    padding: 13px 20px;
    background: rgba(11, 16, 32, .9);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--line);
  }
  header h1 { font-size: 16px; margin: 0; letter-spacing: .3px; white-space: nowrap; }
  header .brand-dot {
    display: inline-block; width: 9px; height: 9px; border-radius: 50%;
    background: var(--accent); margin-right: 9px;
    box-shadow: 0 0 12px var(--accent);
  }
  header .meta { color: var(--muted); font-size: 12px; white-space: nowrap; }
  header .spacer { flex: 1; }
  .alert-chip {
    display: none; align-items: center; gap: 6px;
    font-size: 12px; color: #fecaca; text-decoration: none;
    border: 1px solid rgba(248, 113, 113, .4);
    background: rgba(248, 113, 113, .08);
    padding: 5px 11px; border-radius: 999px; white-space: nowrap;
  }
  .alert-chip:hover { border-color: var(--danger); }
  input[type="search"] {
    width: min(300px, 52vw);
    padding: 8px 12px; border-radius: 9px;
    border: 1px solid var(--line); background: var(--panel);
    color: var(--text); outline: none;
  }
  input[type="search"]:focus { border-color: var(--accent); }
  button {
    padding: 7px 12px; border-radius: 9px; cursor: pointer;
    border: 1px solid var(--line); background: var(--panel-2); color: var(--text);
  }
  button:hover { border-color: var(--accent); }

  .shell {
    display: grid;
    grid-template-columns: 228px minmax(0, 1fr);
    align-items: start;
  }
  .sidebar {
    position: sticky; top: 57px;
    height: calc(100vh - 57px); overflow-y: auto;
    border-right: 1px solid var(--line);
    padding: 14px 10px 28px;
    background: rgba(11, 16, 32, .55);
  }
  .nav-title {
    font-size: 11px; letter-spacing: .08em; color: var(--muted);
    margin: 14px 10px 6px; text-transform: uppercase;
  }
  .nav-title:first-child { margin-top: 2px; }
  .nav-item {
    display: flex; align-items: center; gap: 8px;
    padding: 7px 10px; border-radius: 9px;
    color: #c9d4f2; text-decoration: none; font-size: 13.5px;
    border: 1px solid transparent;
  }
  .nav-item:hover { background: var(--panel); }
  .nav-item.active {
    background: rgba(34, 211, 238, .12);
    border-color: rgba(34, 211, 238, .3);
    color: var(--accent); font-weight: 600;
  }
  .nav-count { margin-left: auto; font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .nav-count.warn { color: var(--danger); }
  .sidebar-foot { margin: 22px 10px 0; color: var(--muted); font-size: 11px; line-height: 1.6; }

  .main { padding: 20px 26px 64px; min-width: 0; }
  .view-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; margin-bottom: 14px; }
  .view-head h2 { margin: 0; font-size: 20px; }
  .view-head .sub { color: var(--muted); font-size: 12.5px; }
  .view-head .topic-meta {
    flex-basis: 100%; color: var(--muted); font-size: 12px;
    font-variant-numeric: tabular-nums;
  }

  .panel {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 14px; padding: 16px 18px; margin-bottom: 16px;
  }
  .panel h3 { margin: 0 0 8px; font-size: 13px; color: var(--muted); font-weight: 600; letter-spacing: .4px; }
  .panel-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }
  .panel-head h3 { margin: 0; }
  .panel-note { color: var(--muted); font-size: 11.5px; }
  .digest-body {
    display: grid; gap: 20px; align-items: start;
    grid-template-columns: minmax(0, 1.6fr) minmax(260px, 1fr);
  }
  .digest-body.single { grid-template-columns: minmax(0, 1fr); }
  .digest-text { white-space: pre-wrap; line-height: 1.75; font-size: 14px; }
  .digest-summary { margin: 0; }
  .digest-warn { margin: 10px 0 0; color: var(--warn); font-size: 12.5px; line-height: 1.6; }
  .digest-points { margin: 0; padding-left: 18px; color: #c9d4f2; font-size: 13.5px; line-height: 1.7; }
  .digest-points li { margin-bottom: 8px; }
  .empty-state {
    border: 1px dashed var(--line); border-radius: 10px;
    padding: 16px 18px; color: var(--muted); font-size: 13px; line-height: 1.8;
  }
  .empty-state strong { color: var(--text); font-weight: 600; }
  .empty-state code {
    color: var(--accent); background: rgba(34, 211, 238, .08);
    padding: 1px 6px; border-radius: 6px; font-size: 12px;
  }

  .items {
    display: grid; gap: 12px; align-items: start;
    grid-template-columns: minmax(0, 1fr);
  }
  .item {
    background: var(--panel); border: 1px solid var(--line); border-radius: 13px;
    padding: 14px 16px; transition: border-color .15s ease, transform .15s ease;
  }
  .item:hover { border-color: var(--accent); transform: translateY(-1px); }
  .item .head { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  .item h4 { margin: 0; font-size: 15.5px; line-height: 1.45; flex: 1; min-width: 240px; }
  .item h4 a { color: var(--text); text-decoration: none; }
  .item h4 a:hover { color: var(--accent); }
  .item .orig { color: var(--muted); font-size: 12px; margin-top: 4px; }
  .item .summary { color: #b7c3e2; font-size: 13.5px; line-height: 1.65; margin-top: 8px; }
  .badges { display: flex; gap: 6px; flex-wrap: wrap; }
  .badge {
    font-size: 11px; color: var(--muted); border: 1px solid var(--line);
    border-radius: 999px; padding: 2px 8px; white-space: nowrap;
  }
  .badge.high { color: var(--ok); border-color: rgba(52, 211, 153, .4); }
  .badge.low { color: var(--warn); border-color: rgba(245, 158, 11, .4); }
  .badge.medium { color: var(--muted); }
  .badge.multi { color: var(--accent); border-color: rgba(34, 211, 238, .45); }
  .badge.score-low { color: var(--danger); border-color: rgba(248, 113, 113, .45); }
  .badge.score-mid { color: var(--warn); border-color: rgba(245, 158, 11, .4); }
  .badge.score-high { color: var(--ok); border-color: rgba(52, 211, 153, .4); }
  .timeline {
    margin-top: 10px; padding: 10px 12px; border-left: 2px solid var(--line);
    display: grid; gap: 8px; font-size: 12.5px;
  }
  .timeline .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: baseline; }
  .timeline .time { color: var(--muted); min-width: 96px; }
  .timeline .row a { color: #c9d4f2; text-decoration: none; }
  .timeline .row a:hover { color: var(--accent); }
  .item details { margin-top: 10px; }
  .item details summary { cursor: pointer; color: var(--muted); font-size: 12px; }
  .empty { color: var(--muted); text-align: center; padding: 48px 0; font-size: 14px; }

  .filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
  .filter {
    border: 1px solid var(--line); background: var(--panel);
    color: var(--muted); padding: 6px 12px; border-radius: 999px; font-size: 12.5px;
  }
  .filter.active { color: #071018; background: var(--accent); border-color: var(--accent); font-weight: 600; }

  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
  th { color: var(--muted); font-weight: 600; white-space: nowrap; }
  td.status-ok { color: var(--ok); white-space: nowrap; }
  td.status-degraded { color: var(--warn); white-space: nowrap; }
  td.status-unavailable { color: var(--danger); white-space: nowrap; }
  td.err { color: #c9a0a0; word-break: break-word; }
  .table-wrap { overflow-x: auto; }
  .hint {
    border: 1px solid rgba(34, 211, 238, .3); background: rgba(34, 211, 238, .07);
    color: #bfeaf5; border-radius: 10px; padding: 10px 14px;
    font-size: 12.5px; line-height: 1.65; margin-bottom: 14px;
  }

  @media (max-width: 860px) {
    .shell { grid-template-columns: 1fr; }
    .sidebar {
      position: static; height: auto; overflow: visible;
      border-right: 0; border-bottom: 1px solid var(--line);
      padding: 10px 12px;
    }
    .nav-title { margin-top: 8px; }
    .sidebar-foot { display: none; }
    .main { padding: 16px 14px 52px; }
    .items, .digest-body { grid-template-columns: minmax(0, 1fr); }
    header .meta { display: none; }
  }
</style>
</head>
<body>
<header>
  <h1><span class="brand-dot"></span>QuotaFuse Wire</h1>
  <span class="meta" id="generated">加载中…</span>
  <span class="spacer"></span>
  <a class="alert-chip" id="alert-chip" href="#/notices"></a>
  <input id="search" type="search" placeholder="搜索标题 / 摘要 / 信源" autocomplete="off" />
  <button id="refresh" type="button">刷新</button>
</header>
<div class="shell">
  <aside class="sidebar">
    <nav id="nav"></nav>
    <div class="sidebar-foot">数据来自本地归档，不联网、不上报。<br />刷新会重新读取 data.js。</div>
  </aside>
  <main class="main" id="view"></main>
</div>
<script>
(function () {
  "use strict";

  var state = { view: "topic", topic: null, query: "", filter: "all" };
  var data = { industries: [] };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function figures() {
    var industries = data.industries || [];
    var items = 0;
    industries.forEach(function (industry) { items += (industry.items || []).length; });
    var sources = data.sourceStatus || [];
    var status = { ok: 0, degraded: 0, unavailable: 0 };
    sources.forEach(function (row) {
      if (status[row.status] !== undefined) status[row.status] += 1;
    });
    var alerts = sources.length
      ? status.degraded + status.unavailable
      : (data.sourceNotice || []).length;
    return { items: items, sources: sources.length, status: status, alerts: alerts };
  }

  function findIndustry(key) {
    var list = data.industries || [];
    for (var i = 0; i < list.length; i += 1) {
      if (list[i].key === key || list[i].id === key) return list[i];
    }
    return null;
  }

  function currentIndustry() {
    var list = data.industries || [];
    if (!list.length) return null;
    var found = state.topic ? findIndustry(state.topic) : null;
    if (found) return found;
    state.topic = list[0].key;
    return list[0];
  }

  function parseHash() {
    var hash = (location.hash || "").replace(/^#\/?/, "");
    var parts = hash.split("/");
    var head = parts[0] || "";
    var tail = parts[1] ? decodeURIComponent(parts[1]) : "";
    if (head === "sources") return { view: "sources", topic: null };
    if (head === "notices") return { view: "notices", topic: null };
    if (head === "topic" && tail) return { view: "topic", topic: tail };
    return { view: "topic", topic: null };
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

  function scoreOf(sourceId) {
    var scores = data.sourceScores || {};
    return scores[sourceId] ? scores[sourceId].score : null;
  }

  function scoreClass(value) {
    if (value >= 0.6) return "status-ok";
    if (value >= 0.45) return "status-degraded";
    return "status-unavailable";
  }

  function reportKey(item) {
    return item.event_id ? "event:" + item.event_id : "item:" + (item.url || item.title);
  }

  function groupReports(items) {
    var groups = [];
    var index = {};
    items.forEach(function (item) {
      var key = reportKey(item);
      if (index[key] !== undefined) {
        groups[index[key]].reports.push(item);
        return;
      }
      index[key] = groups.length;
      groups.push({ lead: item, reports: [item] });
    });
    return groups;
  }

  function renderNav() {
    var nav = document.getElementById("nav");
    var info = figures();
    nav.textContent = "";

    nav.appendChild(el("div", "nav-title", "资讯"));
    (data.industries || []).forEach(function (industry) {
      var link = el("a", "nav-item" + (state.view === "topic" && industry.key === currentIndustryKey() ? " active" : ""));
      link.href = "#/topic/" + encodeURIComponent(industry.key);
      link.appendChild(el("span", null, industry.name || industry.key));
      link.appendChild(el("span", "nav-count", String((industry.items || []).length)));
      nav.appendChild(link);
    });

    nav.appendChild(el("div", "nav-title", "数据"));
    var sources = el("a", "nav-item" + (state.view === "sources" ? " active" : ""));
    sources.href = "#/sources";
    sources.appendChild(el("span", null, "信源状态"));
    sources.appendChild(el("span", "nav-count", String(info.sources)));
    nav.appendChild(sources);

    var notices = el("a", "nav-item" + (state.view === "notices" ? " active" : ""));
    notices.href = "#/notices";
    notices.appendChild(el("span", null, "抓取告警"));
    notices.appendChild(el("span", "nav-count" + (info.alerts ? " warn" : ""), String(info.alerts)));
    nav.appendChild(notices);
  }

  function currentIndustryKey() {
    var industry = currentIndustry();
    return industry ? industry.key : null;
  }

  function renderChrome() {
    var info = figures();
    document.getElementById("generated").textContent = data.generatedAt
      ? "生成于 " + data.generatedAt
      : "暂无数据";
    var chip = document.getElementById("alert-chip");
    if (info.alerts > 0) {
      chip.hidden = false;
      chip.style.display = "inline-flex";
      chip.textContent = "今日 " + info.alerts + " 个信源异常 · 查看";
    } else {
      chip.hidden = true;
      chip.style.display = "none";
    }
    var search = document.getElementById("search");
    var isTopic = state.view === "topic";
    search.hidden = !isTopic;
    search.style.display = isTopic ? "" : "none";
  }

  function viewHead(title, subtitle, meta) {
    var head = el("div", "view-head");
    head.appendChild(el("h2", null, title));
    if (subtitle) head.appendChild(el("span", "sub", subtitle));
    if (meta) head.appendChild(el("div", "topic-meta", meta));
    return head;
  }

  function topicSourceCount(industry) {
    var count = 0;
    (data.sourceStatus || []).forEach(function (row) {
      if (row.topic === industry.id || row.topic === industry.key) count += 1;
    });
    return count;
  }

  function topicMeta(industry) {
    var parts = [];
    var sources = topicSourceCount(industry);
    if (sources) parts.push("共 " + sources + " 个信源");
    parts.push("本栏 " + ((industry.items || []).length) + " 条");
    if (data.generatedAt) parts.push("更新 " + data.generatedAt);
    parts.push("本地抓取");
    return parts.join(" · ");
  }

  function digestState(industry) {
    var summary = (industry && industry.summary) || "";
    var keyPoints = (industry && industry.key_points) || [];
    if (industry && industry.digest_state) return industry.digest_state;
    return (summary || keyPoints.length) ? "ok" : "missing";
  }

  function renderDigest(industry, main) {
    var summary = (industry && industry.summary) || "";
    var keyPoints = (industry && industry.key_points) || [];
    var state = digestState(industry);
    var panel = el("section", "panel");
    var head = el("div", "panel-head");
    head.appendChild(el("h3", null, (industry.name || industry.key || "") + " 今日要点"));
    head.appendChild(el("span", "panel-note", state === "ok" ? "由模型提炼 · 跨源去重" : ""));
    panel.appendChild(head);

    if (state === "missing") {
      var hint = el("div", "empty-state");
      hint.appendChild(el("strong", null, "今日要点尚未生成。"));
      hint.appendChild(document.createTextNode(
        "它由你自己配置的大模型阅读当日资讯后提炼，不是抓取得到的。在仓库根目录的 .env 里填好 QF_WIRE_API_BASE 和 QF_WIRE_API_KEY，"
        + "并在 config/digest.yaml 里设置 provider 与 default_model，然后运行 "
      ));
      hint.appendChild(el("code", null, "qfw digest --topic " + (industry.id || industry.key)));
      hint.appendChild(document.createTextNode(" 即可生成。"));
      panel.appendChild(hint);
      main.appendChild(panel);
      return;
    }

    if (!summary && !keyPoints.length) {
      panel.appendChild(el("div", "empty-state", "本次提炼没有返回内容，可稍后重新运行 qfw digest。"));
      main.appendChild(panel);
      return;
    }

    var body = el("div", "digest-body" + (keyPoints.length ? "" : " single"));
    var text = el("div", "digest-text");
    if (summary) text.appendChild(el("p", "digest-summary", summary));
    if (state === "partial") {
      var reason = industry.digest_error ? "本次提炼失败：" + industry.digest_error : "本次提炼未能完整完成，以下为已采集资讯。";
      text.appendChild(el("p", "digest-warn", reason + " 检查模型地址与密钥后重新运行 qfw digest。"));
    }
    body.appendChild(text);

    if (keyPoints.length) {
      var points = el("ul", "digest-points");
      keyPoints.forEach(function (point) {
        var li = el("li", null, point.text || "");
        var confidence = point.confidence || "medium";
        li.appendChild(document.createTextNode(" "));
        li.appendChild(el("span", "badge " + confidence, confidence));
        points.appendChild(li);
      });
      body.appendChild(points);
    }
    panel.appendChild(body);
    main.appendChild(panel);
  }

  function renderTimeline(group) {
    var wrap = el("div", "timeline");
    var reports = group.reports.slice().sort(function (a, b) {
      return (a.ts || 0) - (b.ts || 0);
    });
    reports.forEach(function (report) {
      var row = el("div", "row");
      row.appendChild(el("span", "time", report.time || "时间未知"));
      row.appendChild(el("span", "badge", report.source || "未知信源"));
      var link = el("a", null, report.zh || report.title || "(无标题)");
      link.href = report.url || "#";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      row.appendChild(link);
      wrap.appendChild(row);
    });
    return wrap;
  }

  function renderItems(industry, main) {
    var items = ((industry && industry.items) || []).filter(matches);
    if (!items.length) {
      main.appendChild(el("div", "empty", state.query ? "没有匹配的资讯" : "该赛道今日暂无资讯"));
      return;
    }
    var wrap = el("div", "items");
    groupReports(items).forEach(function (group) {
      var item = group.lead;
      var card = el("article", "item");
      var head = el("div", "head");
      var title = el("h4");
      var link = el("a", null, item.zh || item.title || "(无标题)");
      link.href = item.url || "#";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      title.appendChild(link);
      head.appendChild(title);

      var badges = el("div", "badges");
      if (item.time) badges.appendChild(el("span", "badge", item.time));
      if (item.source) {
        var score = scoreOf(item.source);
        var sourceBadge = el("span", "badge", item.source);
        if (score !== null && score !== undefined) {
          sourceBadge.textContent = item.source + " · 评分 " + score.toFixed(2);
          sourceBadge.className = "badge " + (score < 0.45 ? "score-low" : (score < 0.6 ? "score-mid" : "score-high"));
        }
        badges.appendChild(sourceBadge);
      }
      var confidence = item.confidence || "medium";
      badges.appendChild(el("span", "badge " + confidence, "置信 " + confidence));

      var seen = {};
      group.reports.forEach(function (report) {
        var sources = report.sources && report.sources.length ? report.sources : [report.source];
        sources.forEach(function (source) { if (source) seen[source] = true; });
      });
      var distinct = Object.keys(seen).length;
      if (distinct > 1) {
        badges.appendChild(el("span", "badge multi", "多源 " + distinct));
      } else if ((item.source_count || 1) > 1) {
        badges.appendChild(el("span", "badge multi", "多源 " + item.source_count));
      }
      head.appendChild(badges);
      card.appendChild(head);

      if (item.zh && item.title && item.zh !== item.title) {
        card.appendChild(el("div", "orig", item.title));
      }
      if (item.summary) card.appendChild(el("div", "summary", item.summary));
      if (group.reports.length > 1) {
        var details = document.createElement("details");
        details.appendChild(el("summary", null, "事件时间线 · " + group.reports.length + " 篇报道"));
        details.appendChild(renderTimeline(group));
        card.appendChild(details);
      }
      wrap.appendChild(card);
    });
    main.appendChild(wrap);
  }

  function renderTopic(main) {
    var industry = currentIndustry();
    if (!industry) {
      main.appendChild(el("div", "empty", "暂无采集数据，请先运行 qfw run"));
      return;
    }
    main.appendChild(viewHead(industry.name || industry.key, null, topicMeta(industry)));
    renderDigest(industry, main);
    renderItems(industry, main);
  }

  function statusText(status) {
    if (status === "ok") return "正常";
    if (status === "degraded") return "降级";
    if (status === "unavailable") return "不可用";
    return status || "未知";
  }

  function renderSources(main) {
    var info = figures();
    var rows = data.sourceStatus || [];
    main.appendChild(viewHead("信源状态", "共 " + rows.length + " 个信源 · 正常 " + info.status.ok + " · 降级 " + info.status.degraded + " · 不可用 " + info.status.unavailable));
    if (!rows.length) {
      main.appendChild(el("div", "empty", "暂无信源状态数据，请先运行 qfw run"));
      return;
    }

    var filters = el("div", "filters");
    [["all", "全部"], ["ok", "正常"], ["degraded", "降级"], ["unavailable", "不可用"]].forEach(function (pair) {
      var count = pair[0] === "all" ? rows.length : info.status[pair[0]];
      var button = el("button", "filter" + (state.filter === pair[0] ? " active" : ""), pair[1] + " " + count);
      button.type = "button";
      button.addEventListener("click", function () {
        state.filter = pair[0];
        render();
      });
      filters.appendChild(button);
    });
    main.appendChild(filters);

    var shown = rows.filter(function (row) {
      return state.filter === "all" || row.status === state.filter;
    });
    if (!shown.length) {
      main.appendChild(el("div", "empty", "该状态下没有信源"));
      return;
    }

    var panel = el("section", "panel");
    var scroll = el("div", "table-wrap");
    var table = document.createElement("table");
    var thead = document.createElement("thead");
    var headRow = document.createElement("tr");
    ["信源", "赛道", "状态", "条目", "尝试", "耗时", "评分", "错误"].forEach(function (label) {
      headRow.appendChild(el("th", null, label));
    });
    thead.appendChild(headRow);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    shown.forEach(function (row) {
      var tr = document.createElement("tr");
      tr.appendChild(el("td", null, row.name || row.id));
      tr.appendChild(el("td", null, row.topic || ""));
      tr.appendChild(el("td", "status-" + (row.status || ""), statusText(row.status)));
      tr.appendChild(el("td", null, row.itemCount === undefined ? "" : row.itemCount));
      tr.appendChild(el("td", null, row.attempts === undefined ? "" : row.attempts));
      tr.appendChild(el("td", null, row.elapsedMs === undefined || row.elapsedMs === null ? "" : Math.round(row.elapsedMs) + " ms"));
      var score = scoreOf(row.id);
      tr.appendChild(el("td", score === null ? "" : scoreClass(score), score === null ? "—" : score.toFixed(2)));
      tr.appendChild(el("td", "err", row.error || ""));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    scroll.appendChild(table);
    panel.appendChild(scroll);
    main.appendChild(panel);
  }

  function renderNotices(main) {
    var rows = (data.sourceStatus || []).filter(function (row) {
      return row.status && row.status !== "ok";
    });
    main.appendChild(viewHead("抓取告警", rows.length ? "共 " + rows.length + " 个信源今日异常" : "今日全部信源正常"));
    main.appendChild(el(
      "div",
      "hint",
      "这些信源今天没有取到内容，不影响其它信源；下一次采集会自动重试。如果要长期跟踪，可在 config/sources.yaml 中调整或停用。"
    ));
    if (!rows.length) {
      main.appendChild(el("div", "empty", "今天没有抓取告警"));
      return;
    }

    var panel = el("section", "panel");
    var scroll = el("div", "table-wrap");
    var table = document.createElement("table");
    var thead = document.createElement("thead");
    var headRow = document.createElement("tr");
    ["信源", "赛道", "状态", "尝试", "原因"].forEach(function (label) {
      headRow.appendChild(el("th", null, label));
    });
    thead.appendChild(headRow);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      tr.appendChild(el("td", null, row.name || row.id));
      tr.appendChild(el("td", null, row.topic || ""));
      tr.appendChild(el("td", "status-" + (row.status || ""), statusText(row.status)));
      tr.appendChild(el("td", null, row.attempts === undefined ? "" : row.attempts));
      tr.appendChild(el("td", "err", row.error || "该源今日不可用"));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    scroll.appendChild(table);
    panel.appendChild(scroll);
    main.appendChild(panel);
  }

  function render() {
    renderChrome();
    renderNav();
    var main = document.getElementById("view");
    main.textContent = "";
    if (state.view === "sources") {
      renderSources(main);
    } else if (state.view === "notices") {
      renderNotices(main);
    } else {
      renderTopic(main);
    }
  }

  function syncRoute() {
    var route = parseHash();
    state.view = route.view;
    if (route.topic) state.topic = route.topic;
    if (state.view !== "topic") state.query = "";
    document.getElementById("search").value = state.query;
    render();
  }

  function load() {
    var previous = document.getElementById("wire-data");
    if (previous) previous.remove();
    var script = document.createElement("script");
    script.id = "wire-data";
    script.src = "/data.js?t=" + Date.now();
    script.onload = function () {
      data = window.DATA || { industries: [] };
      if (data.industries && data.industries.length && !findIndustry(state.topic)) {
        state.topic = data.industries[0].key;
      }
      render();
    };
    script.onerror = function () {
      var main = document.getElementById("view");
      main.textContent = "";
      main.appendChild(el("div", "empty", "无法加载 data.js，请先运行 qfw run"));
    };
    document.body.appendChild(script);
  }

  document.getElementById("search").addEventListener("input", function (event) {
    state.query = event.target.value.trim();
    if (state.view === "topic") render();
  });
  document.getElementById("refresh").addEventListener("click", load);
  document.getElementById("alert-chip").addEventListener("click", function (event) {
    event.preventDefault();
    location.hash = "#/notices";
  });
  window.addEventListener("hashchange", syncRoute);
  setInterval(load, 5 * 60 * 1000);
  syncRoute();
  load();
})();
</script>
</body>
</html>
