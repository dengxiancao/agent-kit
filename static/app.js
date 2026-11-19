/* webchat v2 前端 */
(function () {
  'use strict';

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var ta = $('#ta'), feed = $('#thread'), scrollBox = $('#scroll'),
      sendBtn = $('#send'), listEl = $('#list'), qEl = $('#q');

  var S = {
    sid: null,
    sessions: [],
    msgs: [],
    busy: false,
    running: false,
    ac: null,
    lastSeq: 0,
    ctxLimit: 48000,
    health: {},
    tokenUsed: 0,
    stats: null,
    models: [],
    model: ''
  };
  var selToken = 0;
  var nearBottom = true;

  /* ---------------- 基础 ---------------- */

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function num(n) {
    n = n || 0;
    if (n >= 10000) return (n / 1000).toFixed(1).replace('.0', '') + 'k';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return String(n);
  }

  function limTxt(n) {
    if (!n) return '0';
    return n >= 1000 ? ((n / 1000).toFixed(n % 1000 ? 1 : 0) + 'k') : String(n);
  }

  function secs(ms) {
    if (!ms) return '0s';
    if (ms < 1000) return ms + 'ms';
    if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
    return Math.floor(ms / 60000) + 'm' + Math.round((ms % 60000) / 1000) + 's';
  }

  function dayKey(ts) {
    var d = new Date(ts * 1000), n = new Date();
    var today = new Date(n.getFullYear(), n.getMonth(), n.getDate()).getTime();
    if (d.getTime() >= today) return '今天';
    if (d.getTime() >= today - 864e5) return '昨天';
    if (d.getTime() >= today - 6 * 864e5) return '7 天内';
    return '更早';
  }

  function clock(ts) {
    var d = new Date(ts * 1000), n = new Date();
    var today = new Date(n.getFullYear(), n.getMonth(), n.getDate()).getTime();
    var hm = ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
    if (d.getTime() >= today) return hm;
    if (d.getTime() >= today - 864e5) return '昨天';
    return (d.getMonth() + 1) + '/' + d.getDate();
  }

  var toastEl = null, toastTimer = null;
  function toast(msg) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'toast';
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.classList.add('on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('on'); }, 1600);
  }

  function copyText(t) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(t).then(function () { toast('已复制'); },
        function () { fallbackCopy(t); });
    } else fallbackCopy(t);
  }
  function fallbackCopy(t) {
    var x = document.createElement('textarea');
    x.value = t; x.style.position = 'fixed'; x.style.opacity = '0';
    document.body.appendChild(x); x.select();
    try { document.execCommand('copy'); toast('已复制'); } catch (e) { toast('复制失败'); }
    document.body.removeChild(x);
  }

  async function api(path, opts) {
    var r = await fetch(path, opts || {});
    if (!r.ok) {
      var t = '';
      try { t = (await r.json()).error || ''; } catch (e) { }
      throw new Error(t || ('HTTP ' + r.status));
    }
    return r.json();
  }

  /* ---------------- Markdown ---------------- */

  function inline(s) {
    s = esc(s);
    s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
    s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g,
      '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
    return s;
  }

  var LEVEL = {
    '危险': 'r', '高危': 'r', '严重': 'r', '失败': 'r',
    '特殊': 'y', '中危': 'y', '警告': 'y', '注意': 'y',
    '安全': 'g', '正常': 'g', '低危': 'g', '成功': 'g'
  };

  function cellHtml(c) {
    var t = String(c).trim();
    var k = LEVEL[t];
    if (k) return '<span class="badge ' + k + '">' + esc(t) + '</span>';
    return inline(c);
  }

  function cells(l) {
    return l.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(function (x) { return x.trim(); });
  }

  function mdBlock(t) {
    var lines = t.split('\n'), out = [], i = 0;
    while (i < lines.length) {
      var ln = lines[i];
      if (/^\s*$/.test(ln)) { i++; continue; }

      // 表格
      if (/\|/.test(ln) && i + 1 < lines.length &&
          /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && /-/.test(lines[i + 1])) {
        var head = cells(ln); i += 2; var rows = [];
        while (i < lines.length && /\|/.test(lines[i]) && !/^\s*$/.test(lines[i])) {
          rows.push(cells(lines[i])); i++;
        }
        out.push('<div class="tablewrap"><table><thead><tr>' +
          head.map(function (h) { return '<th>' + inline(h) + '</th>'; }).join('') +
          '</tr></thead><tbody>' +
          rows.map(function (r) {
            return '<tr>' + r.map(function (c) { return '<td>' + cellHtml(c) + '</td>'; }).join('') + '</tr>';
          }).join('') + '</tbody></table></div>');
        continue;
      }

      var m = ln.match(/^(#{1,4})\s+(.*)$/);
      if (m) {
        var n = Math.min(m[1].length + 1, 6);
        out.push('<h' + n + '>' + inline(m[2]) + '</h' + n + '>'); i++; continue;
      }
      if (/^\s*(---|\*\*\*|___)\s*$/.test(ln)) { out.push('<hr>'); i++; continue; }

      if (/^\s*[-*+]\s+/.test(ln)) {
        var it = [];
        while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
          it.push(inline(lines[i].replace(/^\s*[-*+]\s+/, ''))); i++;
        }
        out.push('<ul>' + it.map(function (x) { return '<li>' + x + '</li>'; }).join('') + '</ul>');
        continue;
      }
      if (/^\s*\d+[.)]\s+/.test(ln)) {
        var it2 = [];
        while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
          it2.push(inline(lines[i].replace(/^\s*\d+[.)]\s+/, ''))); i++;
        }
        out.push('<ol>' + it2.map(function (x) { return '<li>' + x + '</li>'; }).join('') + '</ol>');
        continue;
      }
      if (/^\s*>\s?/.test(ln)) {
        var q = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
          q.push(inline(lines[i].replace(/^\s*>\s?/, ''))); i++;
        }
        out.push('<blockquote>' + q.join('<br>') + '</blockquote>');
        continue;
      }

      var p = [];
      while (i < lines.length && !/^\s*$/.test(lines[i]) &&
             !/^\s*(#{1,4}\s|[-*+]\s|\d+[.)]\s|>)/.test(lines[i])) {
        p.push(inline(lines[i])); i++;
      }
      out.push('<p>' + p.join('<br>') + '</p>');
    }
    return out.join('');
  }

  function md(src) {
    var parts = String(src == null ? '' : src).split(/^```/m);
    var html = '';
    for (var i = 0; i < parts.length; i++) {
      if (i % 2 === 1) {
        var body = parts[i], nl = body.indexOf('\n'), lang = '';
        if (nl >= 0) { lang = body.slice(0, nl).trim(); body = body.slice(nl + 1); }
        html += '<div class="codewrap"><div class="codehead"><span class="lg">' +
          esc(lang || 'text') + '</span><span class="sp"></span>' +
          '<button class="cp">复制</button></div><pre><code>' +
          esc(body.replace(/\n$/, '')) + '</code></pre></div>';
      } else {
        html += mdBlock(parts[i]);
      }
    }
    return html;
  }

  /* ---------------- 消息渲染 ---------------- */

  function scroll(force) {
    if (nearBottom || force) scrollBox.scrollTop = scrollBox.scrollHeight;
  }

  function clearThread() { feed.innerHTML = ''; }

  function showEmpty() {
    clearThread();
    var d = document.createElement('div');
    d.className = 'empty';
    d.innerHTML = '<div class="et">今天做什么？</div>' +
      '<div class="es">它能在手机里执行命令、读写文件、分析 APK 和 .so，<br>也能看屏幕、点按钮、识别图片里的字。</div>' +
      '<div class="chips">' +
      '<button>看看工作目录里有什么</button>' +
      '<button>分析一个 APK 的权限和组件</button>' +
      '<button>写个 Python 脚本统计文件大小</button>' +
      '<button>截个屏，看看现在是什么界面</button>' +
      '</div>';
    d.querySelectorAll('button').forEach(function (b) {
      b.onclick = function () {
        ta.value = b.textContent;
        ta.dispatchEvent(new Event('input'));
        send();
      };
    });
    feed.appendChild(d);
  }

  function addUser(text) {
    var empty = $('.empty', feed);
    if (empty) empty.remove();
    var d = document.createElement('div');
    d.className = 'msg u';
    d.innerHTML = '<div class="body">' + esc(text) + '</div>';
    feed.appendChild(d);
    nearBottom = true; scroll(true);
    return d;
  }

  function newBot() {
    var empty = $('.empty', feed);
    if (empty) empty.remove();
    var d = document.createElement('div');
    d.className = 'msg a';
    d.innerHTML = '<div class="ava">A</div><div class="body"></div>';
    feed.appendChild(d);
    scroll();
    return d;
  }

  function thinkTitle(el) {
    var n = el.querySelector('.think-b').textContent.length;
    var tx = el.querySelector('.tx');
    if (el.classList.contains('live')) {
      tx.innerHTML = n ? ('思考中 · ' + n + ' 字') : '思考中…';
    } else {
      tx.textContent = n ? ('思考 · ' + n + ' 字') : '思考';
    }
  }

  function addThink(box, text, live) {
    var body = $('.body', box);
    var el = document.createElement('div');
    el.className = 'think' + (live ? ' open live' : '');
    el.innerHTML = '<div class="think-h"><span class="tx">思考</span>' +
      '<span class="ar">›</span></div><div class="think-b"></div>';
    el.querySelector('.think-h').onclick = function () {
      el._touched = true;
      el.classList.toggle('open');
    };
    el.querySelector('.think-b').textContent = text || '';
    thinkTitle(el);
    body.appendChild(el);
    return el;
  }

  var TOOL_LABEL = { run_shell: 'shell', list_dir: 'ls', read_file: 'read',
                     write_file: 'write', ui: 'ui', rev: 'rev' };

  function argsHint(name, a) {
    a = a || {};
    if (name === 'run_shell') return a.cmd || '';
    if (name === 'ui') return a.cmd || '';
    if (name === 'rev') return (a.action || '') + ' ' + (a.path || '') + (a.extra ? ' ' + a.extra : '');
    if (name === 'list_dir') return (!a.path || a.path === '.') ? '工作目录' : a.path;
    if (a.path) return a.path;
    return '';
  }

  function addTool(box, id, name, args, state) {
    var body = $('.body', box);
    var el = document.createElement('div');
    el.className = 'tool' + (state === 'run' ? ' run' : '') + (state === 'fail' ? ' fail open' : '');
    el.dataset.tid = id || '';
    el.innerHTML =
      '<div class="tool-h">' +
      '<span class="ti">' + (state === 'run' ? '<span class="spin"></span>' :
        state === 'fail' ? '✕' : state === 'ok' ? '✓' : '·') + '</span>' +
      '<span class="tname">' + esc(TOOL_LABEL[name] || name) + '</span>' +
      '<span class="targ">' + esc(argsHint(name, args)) + '</span>' +
      '<span class="tmeta"></span>' +
      '</div><div class="tool-b"><pre></pre></div>';
    el.querySelector('.tool-h').onclick = function () { el.classList.toggle('open'); };
    body.appendChild(el);
    scroll();
    return el;
  }

  function fillTool(id, out, ms, ok) {
    var el = feed.querySelector('.tool[data-tid="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]');
    if (!el) return;
    el.classList.remove('run');
    var ti = el.querySelector('.ti');
    ti.className = 'ti ' + (ok === false ? 'fail' : 'ok');
    ti.innerHTML = ok === false ? '✕' : '✓';
    el.querySelector('.tmeta').textContent = ms ? secs(ms) : '';
    el.querySelector('.tool-b pre').textContent = out || '(无输出)';
    if (ok === false) { el.classList.add('fail', 'open'); }
    if (ok === false) el.querySelector('.tool-b pre').textContent = out || '(无输出)';
  }

  function addText(box, text, raw) {
    var body = $('.body', box);
    var el = document.createElement('div');
    el.className = 'md';
    body.appendChild(el);
    if (raw) { el.classList.add('raw'); el.textContent = text; }
    else el.innerHTML = md(text);
    return el;
  }

  var ICON = {
    copy: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
      '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 012-2h8"/></svg>',
    regen: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">' +
      '<path d="M20 11a8 8 0 10-2.3 5.7"/><path d="M20 4v7h-7"/></svg>',
    branch: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">' +
      '<circle cx="6" cy="5" r="2.2"/><circle cx="6" cy="19" r="2.2"/><circle cx="18" cy="12" r="2.2"/>' +
      '<path d="M6 7.2v9.6M8.2 5h4.3A3.5 3.5 0 0116 8.5v1.3"/></svg>'
  };

  function addFooter(box, meta, opts) {
    opts = opts || {};
    if (!meta) return;
    var parts = [];
    if (meta.steps) parts.push('<span>' + meta.steps + ' 步</span>');
    if (meta.ms) parts.push('<span>' + secs(meta.ms) + '</span>');
    if (meta.tokens) parts.push('<span>' + num(meta.tokens) + ' tokens</span>');
    if (!parts.length && !opts.regen) return;
    var acts = '<button class="cpmsg" title="复制">' + ICON.copy + '</button>' +
      (opts.regen ? '<button class="regen" title="重新生成这一轮">' + ICON.regen + '</button>' : '') +
      (opts.seq ? '<button class="brnch" title="从这里分叉出一个新对话">' + ICON.branch + '</button>' : '');
    var el = document.createElement('div');
    el.className = 'mfoot';
    el.innerHTML = parts.join('<span class="sep">·</span>') +
      '<div class="acts">' + acts + '</div>';
    el.querySelector('.cpmsg').onclick = function () {
      var t = $('.body', box).innerText;
      copyText(t);
    };
    var rg = el.querySelector('.regen');
    if (rg) rg.onclick = function () { regenerate(); };
    var br = el.querySelector('.brnch');
    if (br) br.onclick = function () { branchAt(opts.seq); };
    $('.body', box).appendChild(el);
  }

  function addErr(text) {
    var d = document.createElement('div');
    d.className = 'errbox';
    d.textContent = text;
    feed.appendChild(d);
    scroll(true);
  }

  function addInterrupted() {
    var d = document.createElement('div');
    d.className = 'interrupted';
    d.innerHTML = '<span>任务被中断，没有拿到工具结果。回一句「继续」可以接着跑。</span>';
    feed.appendChild(d);
    scroll();
  }

  function addDivider(text) {
    var d = document.createElement('div');
    d.className = 'divider';
    d.innerHTML = '<span>' + esc(text) + '</span>';
    feed.appendChild(d);
    scroll();
  }

  /* ---------------- 会话列表 ---------------- */

  function renderSessions() {
    var list = S.sessions;
    listEl.innerHTML = '';
    if (!list.length) {
      listEl.innerHTML = '<div class="grp">还没有对话</div>';
      return;
    }
    var groups = {}, order = [];
    list.forEach(function (s) {
      var k = s.pinned ? '置顶' : dayKey(s.updated_at);
      if (!groups[k]) { groups[k] = []; order.push(k); }
      groups[k].push(s);
    });
    if (groups['置顶']) {
      order = order.filter(function (k) { return k !== '置顶'; });
      order.unshift('置顶');
    }
    order.forEach(function (k) {
      var g = document.createElement('div');
      g.className = 'grp';
      g.textContent = k;
      listEl.appendChild(g);
      groups[k].forEach(function (s) { listEl.appendChild(itemEl(s)); });
    });
  }

  function itemEl(s) {
    var d = document.createElement('div');
    d.className = 'item' + (s.id === S.sid ? ' on' : '') +
      (S.runningSid === s.id ? ' run' : '');
    d.dataset.sid = s.id;
    d.innerHTML = '<span class="tt">' + esc(s.title || '新对话') + '</span>' +
      '<span class="mt">' + clock(s.updated_at) + '</span>' +
      '<button class="moar" title="更多">⋯</button>';
    d.onclick = function (e) {
      if (e.target.closest('.moar')) return;
      selectSession(s.id);
    };
    d.querySelector('.moar').onclick = function (e) {
      e.stopPropagation();
      openMenu(s, e.clientX, e.clientY);
    };
    return d;
  }

  var popEl = $('#pop');
  function openMenu(s, x, y) {
    popEl.innerHTML =
      '<button data-a="pin">' + (s.pinned ? '取消置顶' : '置顶') + '</button>' +
      '<button data-a="rename">重命名</button>' +
      '<hr><button data-a="del" class="del">删除</button>';
    popEl.classList.add('on');
    var w = 140, h = 120;
    popEl.style.left = Math.min(x, innerWidth - w - 10) + 'px';
    popEl.style.top = Math.min(y, innerHeight - h - 10) + 'px';
    popEl.querySelectorAll('button').forEach(function (b) {
      b.onclick = async function () {
        var a = b.dataset.a;
        popEl.classList.remove('on');
        if (a === 'pin') {
          await api('/api/sessions/' + s.id, {
            method: 'PATCH', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pinned: !s.pinned })
          });
          loadSessions();
        } else if (a === 'rename') {
          var t = prompt('新标题', s.title || '');
          if (t && t.trim()) {
            await api('/api/sessions/' + s.id, {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ title: t.trim() })
            });
            if (s.id === S.sid) $('#title').textContent = t.trim();
            loadSessions();
          }
        } else if (a === 'del') {
          if (!confirm('删除「' + (s.title || '新对话') + '」？这个会话的消息会一起删掉。')) return;
          await api('/api/sessions/' + s.id, { method: 'DELETE' });
          if (s.id === S.sid) {
            S.sid = null; S.msgs = []; S.stats = null;
            showEmpty(); $('#title').textContent = '新对话';
            if (S.ac) { try { S.ac.abort(); } catch (e) { } S.ac = null; }
          }
          loadSessions();
        }
      };
    });
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest('#pop') && !e.target.closest('.moar') && !e.target.closest('.pick')) {
      popEl.classList.remove('on');
    }
  });

  async function loadSessions(q) {
    try {
      var d = await api('/api/sessions' + (q ? '?q=' + encodeURIComponent(q) : ''));
      S.sessions = d.sessions || [];
      renderSessions();
    } catch (e) { /* 静默 */ }
  }

  /* ---------------- 打开会话 ---------------- */

  function renderHistory(msgs) {
    clearThread();
    if (!msgs.length) { showEmpty(); return; }
    var box = null, acc = null;

    function flushAcc(final) {
      if (box && acc) {
        addFooter(box, acc, {
          regen: !!final && !S.running,
          seq: box._seq || 0
        });
      }
      acc = null;
    }

    msgs.forEach(function (m) {
      if (m.role === 'user') {
        flushAcc();
        addUser(m.content || '');
        box = null;
        return;
      }
      if (m.role === 'assistant') {
        if (!m.content && !m.tool_calls && !m.reasoning) return;
        if (!box) { box = newBot(); acc = { steps: 0, ms: 0, tokens: 0 }; }
        box._seq = m.seq;
        var meta = {};
        try { meta = m.meta ? JSON.parse(m.meta) : {}; } catch (e) { }
        if (m.reasoning) addThink(box, m.reasoning, false);
        if (m.content) addText(box, m.content);
        if (m.tool_calls) {
          var tcs = [];
          try { tcs = JSON.parse(m.tool_calls); } catch (e) { }
          tcs.forEach(function (tc) {
            var a = {};
            try { a = JSON.parse(tc.function.arguments || '{}'); } catch (e) { }
            addTool(box, tc.id, tc.function.name, a, 'idle');
          });
          acc.steps += tcs.length;
        }
        if (meta.steps) acc.steps += meta.steps;
        if (meta.ms) acc.ms += meta.ms;
        if (meta.tokens) acc.tokens += meta.tokens;
        return;
      }
      if (m.role === 'tool') {
        var meta2 = {};
        try { meta2 = m.meta ? JSON.parse(m.meta) : {}; } catch (e) { }
        var ok = meta2.ok !== false && !(m.content || '').startsWith('ERROR:');
        fillTool(m.tool_call_id, m.content, meta2.ms, ok);
        if (box && acc && meta2.ms) acc.ms = Math.max(acc.ms, 0);
        if (m.content && m.content.indexOf('（任务被中断') === 0) addInterrupted();
      }
    });
    flushAcc(true);
    scroll(true);
  }

  async function selectSession(sid, opts) {
    if (!sid || (sid === S.sid && !(opts && opts.force))) return;
    if (S.ac) { try { S.ac.abort(); } catch (e) { } S.ac = null; }
    // 当前空会话切走时顺手清理
    if (S.sid && S.sid !== sid && S.msgs.length === 0) {
      api('/api/sessions/' + S.sid, { method: 'DELETE' }).catch(function () { });
    }
    var my = ++selToken;
    S.sid = sid;
    S.lastSeq = 0;
    document.body.classList.remove('drawer');
    try {
      var d = await api('/api/sessions/' + sid + '/messages');
      if (my !== selToken) return;
      S.msgs = d.messages || [];
      S.running = !!d.running;
      $('#title').textContent = (d.session && d.session.title) || '新对话';
      if (d.session && d.session.model) setModel(d.session.model);
      var list = S.msgs;
      if (S.running) {
        // 正在跑的这一轮以事件流为准，历史里先去掉，避免重复
        for (var i = list.length - 1; i >= 0; i--) {
          if (list[i].role === 'user') { list = list.slice(0, i); break; }
        }
      }
      renderHistory(list);
      renderSessions();
      setState(S.running ? 'run' : 'idle');
      loadStats();
      if (S.running) attachStream(sid, 0);
    } catch (e) {
      addErr('打开会话失败：' + e.message);
    }
  }

  async function newSession(silent) {
    try {
      var d = await api('/api/sessions', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      S.sid = d.id;
      S.msgs = [];
      S.running = false;
      S.lastSeq = 0;
      S.tokenUsed = 0;
      selToken++;
      $('#title').textContent = '新对话';
      showEmpty();
      renderStats(null);
      setState('idle');
      await loadSessions();
      document.body.classList.remove('drawer');
      if (!silent) ta.focus();
      return d.id;
    } catch (e) {
      toast('新建失败：' + e.message);
    }
  }

  /* ---------------- 状态与详情 ---------------- */

  function setState(mode) {
    var chip = $('#chip-state');
    var stopBtn = $('#stopbtn');
    if (mode === 'run') {
      chip.className = 'chip busy';
      chip.innerHTML = '<i class="dot"></i><span>运行中</span>';
      stopBtn.hidden = false;
    } else {
      chip.className = 'chip ok';
      chip.innerHTML = '<i class="dot"></i><span>空闲</span>';
      stopBtn.hidden = true;
    }
  }

  async function loadStats() {
    if (!S.sid) return;
    try {
      var st = await api('/api/sessions/' + S.sid + '/stats');
      S.stats = st;
      if (st.model) setModel(st.model);
      renderStats(st);
    } catch (e) { }
  }

  function renderStats(st) {
    var ctx = st ? (st.ctx || 0) : 0;
    var pct = Math.min(100, Math.round(ctx / S.ctxLimit * 100));
    var pctTxt = (ctx > 0 && pct === 0) ? '<1%' : pct + '%';
    var chip = $('#chip-ctx span');
    if (chip) chip.textContent = '上下文 ' + num(ctx) + ' / ' + limTxt(S.ctxLimit);
    $('#chip-ctx').className = 'chip hide-m' + (pct > 85 ? ' warn' : '');

    if (!st) { $('#insbody').innerHTML = ''; $('#insfoot').innerHTML = ''; return; }

    var bars = pct > 85 ? 'd' : pct > 70 ? 'w' : '';
    var html = '';
    html += '<div class="card"><div class="ch">上下文<span class="r">' + pctTxt + '</span></div>' +
      '<div class="bar"><i class="' + bars + '" style="width:' + Math.max(pct, 2) + '%"></i></div>' +
      '<div class="mini"><span>' + num(ctx) + ' tokens</span><span>上限 ' + limTxt(S.ctxLimit) + '</span></div>' +
      '<div style="height:9px"></div>' +
      '<div class="kv"><span>消息</span><b>' + st.messages + ' 条</b></div>' +
      '<div class="kv"><span>工具调用</span><b>' + st.steps + ' 次</b></div>' +
      '<div class="kv"><span>累计 token</span><b>' + num(st.tokens) + '</b></div>' +
      '<div class="kv"><span>剩余额度</span><b>' + num(Math.max(0, Math.round(S.ctxLimit * 0.85 - ctx))) + ' tokens</b></div>' +
      (st.compacted ? '<div class="kv"><span>已折叠</span><b>' + st.compacted_msgs +
        ' 条 → 摘要 ' + num(st.summary_chars) + ' 字</b></div>' : '') +
      (st.messages > 2 ? '<button class="insbtn" data-act="compact">' +
        (st.compacted ? '再压一次' : '压缩上下文') + '</button>' : '') +
      '</div>';

    html += '<div class="card"><div class="ch">累计用量' +
      (S.running ? '<span class="r" style="color:var(--brand)">运行中</span>' : '') + '</div>' +
      '<div class="kv"><span>输入</span><b>' + num(st.tokens_in) + '</b></div>' +
      '<div class="kv"><span>输出</span><b>' + num(st.tokens_out) + '</b></div>' +
      '<div class="kv"><span>估算费用</span><b>¥' + (st.tokens_in / 1e6 * 1 + st.tokens_out / 1e6 * 2).toFixed(3) + '</b></div>' +
      '</div>';

    if (st.tools && st.tools.length) {
      html += '<div class="card"><div class="ch">最近工具</div><div class="tl">';
      st.tools.slice().reverse().forEach(function (t) {
        var f = t.meta && t.meta.ok === false;
        html += '<div class="tli' + (f ? ' f' : '') + '"><div class="n">' +
          esc(TOOL_LABEL[t.name] || t.name) +
          '<span>' + (t.meta && t.meta.ms ? secs(t.meta.ms) : '') + '</span></div>' +
          '<div class="d">' + (f ? '失败' : '成功') + '</div></div>';
      });
      html += '</div></div>';
    }

    html += '<div class="card"><div class="ch">环境</div>' +
      '<div class="kv"><span>模型</span><b>' + esc(st.model || '') + '</b></div>' +
      '<div class="kv"><span>单轮上限</span><b>' + (S.health.max_turns || 100) + ' 步</b></div>' +
      '<div class="kv"><span>工具</span><b>6 个</b></div>' +
      '<div class="kv"><span>存储</span><b>' + (S.health.db_size ? (S.health.db_size / 1024).toFixed(0) + ' KB' : '—') + '</b></div>' +
      '<button class="insbtn" data-act="clean">存储与清理</button>' +
      '</div>';

    $('#insbody').innerHTML = html;
    $('#insfoot').innerHTML = '工作目录<span class="p">' + esc(st.work || '') + '</span>' +
      (S.health.db ? '存储<span class="p">' + esc(S.health.db.replace(/^.*\//, '~/…/')) + '</span>' : '');
  }

  /* ---------------- 事件流 ---------------- */

  var A = null;   // 本轮渲染上下文

  function beginTurn() {
    A = { box: null, think: null, text: null, raf: null, raw: '', tools: 0, t0: Date.now() };
  }

  function ensureTurn() {
    if (!A) beginTurn();
    return A;
  }

  function ensureBot() {
    if (!A.box) A.box = newBot();
    return A.box;
  }

  function flushText() {
    if (!A) return;
    A.raf = null;
    if (!A.text) return;
    A.text.innerHTML = md(A.raw);
    scroll();
  }

  function scheduleText() {
    if (!A.raf) A.raf = requestAnimationFrame(flushText);
  }

  function onEvent(ev, sid) {
    if (sid && sid !== S.sid) return;
    switch (ev.t) {
      case 'user':
        if (S.pendingUser === ev.v) { S.pendingUser = null; break; }
        addUser(ev.v);
        break;
      case 'title':
        $('#title').textContent = ev.v;
        loadSessions();
        break;
      case 'model':
        setModel(ev.v);
        break;
      case 'compact':
        addDivider('上下文已压缩 · ' + ev.removed + ' 条并入摘要，剩 ' + ev.kept + ' 条');
        break;
      case 'think':
        ensureTurn();
        if (!A.think) A.think = addThink(ensureBot(), '', true);
        A.think.classList.add('open', 'live');
        A.think.querySelector('.think-b').textContent += ev.v;
        thinkTitle(A.think);
        scroll();
        break;
      case 'delta':
        ensureTurn();
        if (!A.text) A.text = addText(ensureBot(), '', true);
        A.raw += ev.v;
        if (A.raw.length > 12000) {
          A.text.textContent = A.raw;   // 太长就不反复渲染 md
          scroll();
        } else scheduleText();
        break;
      case 'tool':
        ensureTurn();
        ensureBot();
        if (A.think) {
          A.think.classList.remove('live');
          thinkTitle(A.think);
          if (!A.think._touched) A.think.classList.remove('open');
          A.think = null;
        }
        A.text = null;
        A.raw = '';
        A.tools++;
        addTool(A.box, ev.id, ev.name, ev.args, 'run');
        break;
      case 'tool_end':
        fillTool(ev.id, ev.out, ev.ms, ev.ok);
        scroll();
        break;
      case 'usage':
        S.tokenUsed = (ev.in || 0) + (ev.out || 0);
        break;
      case 'error':
        addErr(ev.v);
        break;
      case 'done':
        if (A && A.raf) { cancelAnimationFrame(A.raf); A.raf = null; }
        if (A && A.text) flushText();
        if (A && A.think) {
          A.think.classList.remove('live');
          thinkTitle(A.think);
          if (!A.think._touched) A.think.classList.remove('open');
        }
        if (A && A.box) {
          addFooter(A.box, {
            steps: ev.steps, ms: ev.ms || (Date.now() - A.t0),
            tokens: ev.tokens ? (ev.tokens.out || (ev.tokens.in + ev.tokens.out)) : 0
          }, { regen: true });
        }
        A = null;
        S.running = false;
        setState('idle');
        if (ev.hit_limit) toast('已到单轮步数上限，回「继续」可接着跑');
        if (ev.stopped) toast('已停止');
        refreshSessionMeta();
        break;
    }
  }

  async function refreshSessionMeta() {
    if (!S.sid) return;
    try {
      var d = await api('/api/sessions/' + S.sid + '/messages');
      S.msgs = d.messages || [];
      attachBranchLast();
      loadStats();
      loadSessions();
    } catch (e) { }
  }

  /* 刚落地的这一轮是流式渲染的，当时还不知道 seq；跑完补一个分叉按钮 */
  function attachBranchLast(seq) {
    var boxes = feed.querySelectorAll('.msg.a');
    if (!boxes.length) return;
    var acts = boxes[boxes.length - 1].querySelector('.mfoot .acts');
    if (!acts || acts.querySelector('.brnch')) return;
    var s = seq;
    if (!s) {
      for (var i = S.msgs.length - 1; i >= 0; i--) {
        if (S.msgs[i].role === 'assistant') { s = S.msgs[i].seq; break; }
      }
    }
    if (!s) return;
    var btn = document.createElement('button');
    btn.className = 'brnch';
    btn.title = '从这里分叉出一个新对话';
    btn.innerHTML = ICON.branch;
    btn.onclick = function () { branchAt(s); };
    acts.appendChild(btn);
  }

  async function readSSE(resp, sid) {
    var rd = resp.body.getReader(), dec = new TextDecoder(), buf = '';
    while (true) {
      var r = await rd.read();
      if (r.done) break;
      buf += dec.decode(r.value, { stream: true });
      var k;
      while ((k = buf.indexOf('\n\n')) >= 0) {
        var chunk = buf.slice(0, k); buf = buf.slice(k + 2);
        var lines = chunk.split('\n');
        for (var i = 0; i < lines.length; i++) {
          var line = lines[i];
          if (line.indexOf('data:') !== 0) continue;
          var ev;
          try { ev = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }
          onEvent(ev, sid);
        }
      }
    }
  }

  async function attachStream(sid, lastSeq) {
    var my = selToken;
    try {
      var r = await fetch('/api/sessions/' + sid + '/stream?last_seq=' + (lastSeq || 0));
      if (!r.ok) return;
      setState('run');
      S.running = true;
      await readSSE(r, sid);
      if (my === selToken) { S.running = false; setState('idle'); }
    } catch (e) { }
  }

  /* ---------------- 发送 ---------------- */

  async function send() {
    var text = ta.value.trim();
    if (!text || S.busy) return;
    if (!S.sid) {
      var id = await newSession(true);
      if (!id) return;
    }
    if (S.running) { toast('当前会话还在运行，等它跑完或先停止'); return; }

    ta.value = ''; ta.style.height = 'auto';
    sendBtn.disabled = true;
    S.busy = true; S.running = true;
    setState('run');
    beginTurn();
    addUser(text);
    S.pendingUser = text;

    var sid = S.sid;
    S.ac = new AbortController();
    try {
      var r = await fetch('/api/sessions/' + sid + '/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
        signal: S.ac.signal
      });
      if (r.status === 409) { toast('这个会话正在运行'); return; }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      await readSSE(r, sid);
    } catch (e) {
      if (e.name === 'AbortError') return;
      addErr('连接失败：' + e.message);
      setState('idle');
    } finally {
      S.busy = false;
      S.running = false;
      S.ac = null;
      setState('idle');
      sendBtn.disabled = !ta.value.trim();
      refreshSessionMeta();
    }
  }

  /* ---------------- 模型 / 重新生成 / 分支 ---------------- */

  function setModel(v) {
    if (!v) return;
    S.model = v;
    $('#chip-model').textContent = v;
    $('#lbl-model span').textContent = v;
  }

  function pickModel(anchor) {
    var list = (S.models && S.models.length) ? S.models : [S.model || 'deepseek-chat'];
    popEl.innerHTML = list.map(function (m) {
      return '<button data-m="' + esc(m) + '"><span>' + esc(m) + '</span>' +
        (m === S.model ? '<span class="cur">✓</span>' : '') + '</button>';
    }).join('');
    popEl.classList.add('on');
    var r = anchor.getBoundingClientRect();
    var h = popEl.offsetHeight || 96;
    var top = r.bottom + 6;
    if (top + h > innerHeight - 8) top = Math.max(8, r.top - h - 6);
    popEl.style.left = Math.max(8, Math.min(r.left, innerWidth - 190)) + 'px';
    popEl.style.top = top + 'px';
    popEl.querySelectorAll('button').forEach(function (b) {
      b.onclick = async function () {
        popEl.classList.remove('on');
        var m = b.dataset.m;
        setModel(m);
        if (S.sid) {
          try {
            await api('/api/sessions/' + S.sid, {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ model: m })
            });
            toast('已切换到 ' + m);
          } catch (e) { toast('切换失败：' + e.message); }
        } else {
          toast('新会话将使用 ' + m);
        }
        loadStats();
      };
    });
  }

  function removeLastTurn() {
    var us = feed.querySelectorAll('.msg.u');
    if (!us.length) { clearThread(); return; }
    var n = us[us.length - 1];
    while (n) {
      var nx = n.nextElementSibling;
      n.remove();
      n = nx;
    }
  }

  async function regenerate() {
    if (!S.sid || S.running || S.busy) return;
    if (!confirm('重新生成最后一轮？这一轮的回复会被替换掉。')) return;
    var sid = S.sid;
    S.busy = true; S.running = true;
    try {
      var r = await fetch('/api/sessions/' + sid + '/regenerate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
      });
      if (r.status === 409) { toast('这个会话正在运行'); return; }
      if (!r.ok) {
        var t = '';
        try { t = (await r.json()).error || ''; } catch (e) { }
        toast(t || ('HTTP ' + r.status));
        return;
      }
      removeLastTurn();
      setState('run');
      beginTurn();
      await readSSE(r, sid);
    } catch (e) {
      if (e.name !== 'AbortError') addErr('重新生成失败：' + e.message);
    } finally {
      S.busy = false; S.running = false;
      setState('idle');
      refreshSessionMeta();
    }
  }

  async function branchAt(seq) {
    if (!S.sid || S.running || S.busy) return;
    try {
      var d = await api('/api/sessions/' + S.sid + '/branch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(seq ? { seq: seq } : {})
      });
      await loadSessions();
      selectSession(d.id);
      toast('已从这条回复分叉');
    } catch (e) { toast('分支失败：' + e.message); }
  }

  /* ---------------- 弹层：存储清理 ---------------- */

  var sheetEl = $('#sheet'), sheetCard = $('#sheetcard');

  function openSheet(html) {
    sheetCard.innerHTML = html;
    sheetEl.hidden = false;
    document.body.classList.add('sheet-open');
  }

  function closeSheet() {
    sheetEl.hidden = true;
    document.body.classList.remove('sheet-open');
  }

  async function openClean() {
    var o = {};
    try { o = await api('/api/overview'); } catch (e) { }
    var mb = function (n) { return (n / 1048576).toFixed(2) + ' MB'; };
    openSheet(
      '<div class="sh-h"><b>存储</b><button class="iconbtn" data-a="close">' +
      '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>' +
      '</button></div>' +
      '<div class="sh-b">' +
      '<div class="kv"><span>会话</span><b>' + (o.sessions || 0) + ' 个（空会话 ' + (o.empty || 0) + '）</b></div>' +
      '<div class="kv"><span>消息</span><b>' + (o.messages || 0) + ' 条</b></div>' +
      '<div class="kv"><span>占用</span><b>' + mb(o.db_size || 0) + '</b></div>' +
      '<div class="kv"><span>最老的一条</span><b>' + (o.oldest ? new Date(o.oldest * 1000).toLocaleDateString() : '—') + '</b></div>' +
      '<label class="fld"><span>删掉多少天没动过的会话</span>' +
      '<input id="cdays" type="number" min="1" max="3650" value="30"></label>' +
      '<label class="chk"><input id="cempty" type="checkbox" checked> 同时清理空会话</label>' +
      '<div class="sh-note" id="cnote">置顶的会话不会被删。删除不可恢复，建议先「预览」。</div>' +
      '</div>' +
      '<div class="sh-f"><button class="ghost" data-a="dry">预览</button>' +
      '<button class="danger" data-a="run">清理</button></div>'
    );
  }

  async function doClean(dry) {
    var days = parseInt(($('#cdays') || {}).value || '30', 10) || 30;
    var empty = ($('#cempty') || {}).checked !== false;
    var note = $('#cnote');
    note.textContent = dry ? '正在统计…' : '正在清理…';
    try {
      var r = await api('/api/cleanup', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days: days, empty: empty, dry: dry })
      });
      if (dry) {
        note.textContent = r.would_delete
          ? '会删掉 ' + r.would_delete + ' 个会话，当前占用 ' + (r.db_size / 1048576).toFixed(2) + ' MB。'
          : '没有符合条件的会话。';
      } else {
        note.textContent = '已删 ' + r.deleted + ' 个会话，回收 ' +
          (r.freed / 1048576).toFixed(2) + ' MB。';
        toast('清理完成，回收 ' + (r.freed / 1048576).toFixed(2) + ' MB');
        await loadSessions();
        if (S.sid && !S.sessions.some(function (s) { return s.id === S.sid; })) {
          S.sid = null; S.msgs = []; S.stats = null;
          showEmpty();
          $('#title').textContent = '新对话';
          renderStats(null);
          setState('idle');
        } else {
          loadStats();
        }
      }
    } catch (e) {
      note.textContent = '失败：' + e.message;
    }
  }

  sheetCard.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-a]');
    if (!b) return;
    var a = b.dataset.a;
    if (a === 'close') closeSheet();
    else if (a === 'dry') doClean(true);
    else if (a === 'run') {
      if (confirm('确定删除？删掉的会话无法恢复。')) doClean(false);
    }
  });
  sheetEl.addEventListener('click', function (e) {
    if (e.target === sheetEl) closeSheet();
  });

  /* ---------------- 交互 ---------------- */

  ta.addEventListener('input', function () {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 132) + 'px';
    sendBtn.disabled = !ta.value.trim() || S.busy;
  });
  ta.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (ta.value.trim()) send();
    }
  });
  ta.addEventListener('focus', function () { $('#cbox').classList.add('focus'); });
  ta.addEventListener('blur', function () { $('#cbox').classList.remove('focus'); });
  sendBtn.onclick = send;

  scrollBox.addEventListener('scroll', function () {
    nearBottom = scrollBox.scrollHeight - scrollBox.scrollTop - scrollBox.clientHeight < 100;
  }, { passive: true });

  // 主题：auto → dark → light
  var themeBtn = $('#theme');
  var THEMES = ['auto', 'dark', 'light'];
  var themeIdx = 0;
  try {
    var saved = localStorage.getItem('webchat-theme');
    themeIdx = Math.max(0, THEMES.indexOf(saved || 'auto'));
  } catch (e) { }
  function applyTheme() {
    var t = THEMES[themeIdx];
    if (t === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', t);
    themeBtn.title = '主题：' + ({ auto: '跟随系统', dark: '深色', light: '浅色' })[t];
    try { localStorage.setItem('webchat-theme', t); } catch (e) { }
  }
  themeBtn.onclick = function () {
    themeIdx = (themeIdx + 1) % THEMES.length;
    applyTheme();
    toast('主题：' + ({ auto: '跟随系统', dark: '深色', light: '浅色' })[THEMES[themeIdx]]);
  };
  applyTheme();

  $('#newbtn').onclick = function () { newSession(); };
  $('#chip-model').onclick = function () { pickModel(this); };
  $('#lbl-model').onclick = function () { pickModel(this); };
  $('#cleanbtn').onclick = openClean;
  $('#menu').onclick = function () { document.body.classList.toggle('drawer'); };
  $('#scrim').onclick = function () {
    document.body.classList.remove('drawer');
    document.body.classList.remove('ins');
  };
  $('#insbtn').onclick = function () { document.body.classList.add('ins'); };
  $('#insclose').onclick = function () { document.body.classList.remove('ins'); };
  $('#stopbtn').onclick = async function () {
    if (!S.sid) return;
    await api('/api/sessions/' + S.sid + '/stop', { method: 'POST', body: '{}' }).catch(function () { });
    toast('正在停止…');
  };

  var qTimer = null;
  qEl.addEventListener('input', function () {
    clearTimeout(qTimer);
    qTimer = setTimeout(function () { loadSessions(qEl.value.trim()); }, 260);
  });

  $('#insbody').addEventListener('click', async function (e) {
    var b = e.target.closest('[data-act]');
    if (!b) return;
    var act = b.dataset.act;
    if (act === 'clean') return openClean();
    if (act === 'compact') {
      if (!S.sid || S.running || S.busy) { toast('先等这一轮跑完'); return; }
      b.disabled = true;
      b.textContent = '压缩中…';
      try {
        var r = await api('/api/sessions/' + S.sid + '/compact', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
        });
        toast(r.ok ? ('已折叠 ' + r.removed + ' 条 · ' + r.before + ' → ' + r.after + ' tokens')
          : (r.hint || '暂时不用压缩'));
        loadStats();
      } catch (err) {
        toast('压缩失败：' + err.message);
        b.disabled = false;
        b.textContent = '压缩上下文';
      }
    }
  });

  $('#exportbtn').onclick = function () {
    if (!S.msgs.length) { toast('这个会话还没有内容'); return; }
    var out = ['# ' + ($('#title').textContent || '对话'), ''];
    S.msgs.forEach(function (m) {
      if (m.role === 'user') out.push('## 我', '', m.content || '', '');
      else if (m.role === 'assistant' && m.content) out.push('## Agent', '', m.content, '');
      else if (m.role === 'tool') out.push('<details><summary>工具结果</summary>', '', '```',
        (m.content || '').slice(0, 3000), '```', '', '</details>', '');
    });
    var blob = new Blob([out.join('\n')], { type: 'text/markdown' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (($('#title').textContent || 'chat').replace(/[\\/:*?"<>|]/g, '_')) + '.md';
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 3000);
    toast('已导出');
  };

  document.addEventListener('click', function (e) {
    var cp = e.target.closest('.cp');
    if (cp) {
      var code = cp.closest('.codewrap').querySelector('code').textContent;
      copyText(code);
    }
  });

  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault(); newSession();
    }
    if (e.key === 'Escape') {
      document.body.classList.remove('drawer', 'ins');
      popEl.classList.remove('on');
      closeSheet();
    }
  });

  /* ---------------- 启动 ---------------- */

  async function boot() {
    try {
      S.health = await api('/api/health');
      S.models = S.health.models || [];
      S.ctxLimit = S.health.ctx_limit || 48000;
      setModel(S.health.model || 'deepseek-chat');
      $('#ver').textContent = 'v' + (S.health.version || '2');
      $('#footinfo').textContent = S.health.mock ? 'MOCK 演示模式' : (S.health.work || 'local');
      $('#lbl-work').textContent = (S.health.work || '').replace(/^.*\//, '~/…/');
      $('#hint').innerHTML = '工作目录 <span class="k">' +
        esc((S.health.work || '').replace(/^.*\//, '~/…/')) + '</span> · 单轮上限 <span class="k">' +
        (S.health.max_turns || 100) + ' 步</span> · <span class="k">Enter</span> 发送，<span class="k">Shift+Enter</span> 换行';
    } catch (e) { }

    await loadSessions();
    if (S.sessions.length) {
      selectSession(S.sessions[0].id);
    } else {
      showEmpty();
      renderStats(null);
    }
    ta.focus();
  }

  boot();
})();
