"""网页手柄页面 — 由 RemoteController 的本地 HTTP 服务提供给 iPhone 浏览器。"""

from __future__ import annotations

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no, viewport-fit=cover, interactive-widget=resizes-content">
<meta name="theme-color" content="#0e1014">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>uremote</title>
<style>
  :root {
    color-scheme: dark;
    --bg: #0e1014;
    --fg: #e8eaed;
    --muted: #8a919c;
    --glass-border: rgba(255, 255, 255, .22);
  }
  * {
    box-sizing: border-box;
    -webkit-tap-highlight-color: transparent;
    -webkit-touch-callout: none;
    -webkit-user-select: none;
    user-select: none;
  }
  html { background: #0e1014; }
  html, body { margin: 0; padding: 0; height: 100%; overflow: hidden; }
  body {
    background:
      radial-gradient(circle at 18% 10%, rgba(255, 255, 255, .09), transparent 46%),
      radial-gradient(circle at 82% 16%, rgba(255, 255, 255, .06), transparent 44%),
      radial-gradient(circle at 50% 96%, rgba(255, 255, 255, .07), transparent 50%),
      linear-gradient(180deg, #1b1e24, #0c0e11);
    color: var(--fg);
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    display: flex;
    flex-direction: column;
    height: 100dvh;
  }
  button { border: none; cursor: pointer; touch-action: manipulation; padding: 0; }

  .glass {
    background: linear-gradient(180deg, rgba(255, 255, 255, .15) 0%, rgba(255, 255, 255, .03) 45%, rgba(255, 255, 255, .07) 100%);
    -webkit-backdrop-filter: blur(30px) saturate(1.8) brightness(1.08);
    backdrop-filter: blur(30px) saturate(1.8) brightness(1.08);
    border: 1px solid var(--glass-border);
    box-shadow:
      inset 0 1px 1px rgba(255, 255, 255, .42),
      inset 0 -1px 1px rgba(255, 255, 255, .06),
      0 10px 32px rgba(0, 0, 0, .5);
  }

  /* ── 配对浮层 ── */
  #pairing {
    position: fixed; inset: 0; z-index: 30;
    background: var(--bg);
    display: none;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 18px;
    padding: 24px;
  }
  #pairing.show { display: flex; }
  #code { font-size: 52px; font-weight: 700; letter-spacing: 10px; font-variant-numeric: tabular-nums; }
  #pairing .hint { color: var(--muted); font-size: 13px; text-align: center; }
  #confirm-btn {
    background: rgba(255, 255, 255, .92);
    color: #111;
    padding: 12px 40px;
    font-weight: 600;
    border-radius: 999px;
  }
  #confirm-btn:active { opacity: .8; }

  /* ── 主界面 ── */
  #main { display: none; flex: 1; min-height: 0; flex-direction: column; padding: 8px 8px 10px; gap: 8px; }
  #main.show { display: flex; }

  #status { text-align: center; font-size: 12px; color: var(--muted); }
  #status .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; background: rgba(255, 255, 255, .7); }

  /* 上半部分：记录框 */
  #records-box {
    flex: 1; min-height: 0;
    border-radius: 16px;
    padding: 10px 16px 10px 12px;  /* 右侧多留白，避免滚动条遮挡文字 */
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }
  #records-box .title { font-size: 12px; color: var(--muted); margin-bottom: 6px; }
  #records-box .empty { color: var(--muted); font-size: 13px; }
  #records {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  #records-box .item {
    font-size: 13px;
    color: var(--fg);
    padding: 0;
    word-break: break-all;
  }

  /* ── 手柄控制区（Game Boy 布局）── */
  #controls { flex-shrink: 0; display: flex; flex-direction: column; gap: 12px; padding: 0 0; }

  .pad-row { display: flex; align-items: center; justify-content: center; gap: 40px; padding: 0; }

  /* 圆形方向盘：一个圆，整个圆面四等分为扇形按压区 */
  .dpad {
    position: relative;
    width: 150px; height: 150px;
    border-radius: 50%;
    overflow: hidden;
  }
  .zone {
    position: absolute;
    inset: 0;
    background: transparent;
    padding: 0;
  }
  .zone.up { clip-path: polygon(50% 50%, 0 0, 100% 0); }
  .zone.down { clip-path: polygon(50% 50%, 100% 100%, 0 100%); }
  .zone.left { clip-path: polygon(50% 50%, 0 100%, 0 0); }
  .zone.right { clip-path: polygon(50% 50%, 100% 0, 100% 100%); }
  .d-icon {
    position: absolute;
    width: 22px; height: 22px;
    pointer-events: none;
    color: rgba(255, 255, 255, .92);
    transition: opacity .08s ease;
  }
  .d-icon svg { width: 100%; height: 100%; }
  .d-icon.up { top: 13px; left: 64px; }
  .d-icon.down { bottom: 13px; left: 64px; }
  .d-icon.left { left: 13px; top: 64px; }
  .d-icon.right { right: 13px; top: 64px; }
  .zone.up:active ~ .d-icon.up { opacity: .35; }
  .zone.down:active ~ .d-icon.down { opacity: .35; }
  .zone.left:active ~ .d-icon.left { opacity: .35; }
  .zone.right:active ~ .d-icon.right { opacity: .35; }

  /* AB 键：Game Boy 式斜向排列，隐形热区外扩 */
  .ab-row { position: relative; width: 138px; height: 124px; }
  .ab {
    position: absolute;
    width: 62px; height: 62px;
    border-radius: 50%;
    font-size: 24px;
    font-weight: 700;
    color: #fff;
  }
  .ab::after { content: ""; position: absolute; inset: -14px; }
  .ab.a { top: 0; right: 0; }
  .ab.b { bottom: 0; left: 0; }
  .ab:active { transform: scale(.9); }

  /* SELECT / START 风格功能键（底部居中，两键高度不同），隐形热区外扩 */
  .select-row { display: flex; justify-content: center; gap: 26px; }
  .select-item:nth-child(2) { transform: translateY(16px); }
  .oval {
    position: relative;
    width: 58px; height: 26px;
    border-radius: 999px;
    display: flex; align-items: center; justify-content: center;
    color: rgba(255, 255, 255, .92);
  }
  .oval::after { content: ""; position: absolute; inset: -16px; }
  .oval svg { width: 15px; height: 15px; }
  .oval.shift-on { background: rgba(255, 255, 255, .3); }

  /* ── 文本输入条（固定底部，键盘弹出时置于键盘上方）── */
  #textbar {
    display: none;
    position: fixed;
    left: 0; right: 0; bottom: 0;
    z-index: 20;
    padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
    background: rgba(18, 20, 26, .62);
    -webkit-backdrop-filter: blur(26px) saturate(1.35);
    backdrop-filter: blur(26px) saturate(1.35);
    border-top: 1px solid var(--glass-border);
    gap: 10px;
    align-items: center;
  }
  #textbar.show { display: flex; }
  #text-input {
    flex: 1;
    background: rgba(255, 255, 255, .08);
    border: 1px solid var(--glass-border);
    border-radius: 12px;
    color: var(--fg);
    font-size: 16px;
    padding: 10px 12px;
    outline: none;
    -webkit-user-select: text;
    user-select: text;
  }
  .tbtn {
    height: 40px;
    padding: 0 16px;
    border-radius: 999px;
    display: flex; align-items: center; justify-content: center;
    color: var(--fg);
    font-size: 14px;
  }
  .tbtn svg { width: 18px; height: 18px; }
  .tbtn.primary { background: rgba(255, 255, 255, .92); color: #111; }
</style>
</head>
<body>
  <div id="pairing">
    <div class="hint">配对码</div>
    <div id="code">----</div>
    <div class="hint">请确认游戏端屏幕显示的配对码与此一致</div>
    <button id="confirm-btn">确认连接</button>
  </div>

  <div id="main">
    <div id="status"><span class="dot"></span><span id="status-text">已连接</span></div>

    <div id="records-box" class="glass">
      <div class="title">记录</div>
      <div id="records" class="empty">暂无记录</div>
    </div>

    <div id="controls">
      <div class="pad-row">
        <div class="dpad glass">
          <button class="zone up" data-key="k"></button>
          <button class="zone left" data-key="h"></button>
          <button class="zone right" data-key="l"></button>
          <button class="zone down" data-key="j"></button>
          <span class="d-icon up"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 15l7-7 7 7"/></svg></span>
          <span class="d-icon left"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7"/></svg></span>
          <span class="d-icon right"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7"/></svg></span>
          <span class="d-icon down"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 9l7 7 7-7"/></svg></span>
        </div>

        <div class="ab-row">
          <button class="ab glass b">B</button>
          <button class="ab glass a">A</button>
        </div>
      </div>

      <div class="select-row">
        <button class="oval glass" id="key-i">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <rect x="2.5" y="5" width="19" height="14" rx="2.5"/>
            <path d="M6 8.5h.01M9.5 8.5h.01M13 8.5h.01M16.5 8.5h.01M6 11.5h.01M9.5 11.5h.01M13 11.5h.01M16.5 11.5h.01"/>
            <path d="M7.5 15h9"/>
          </svg>
        </button>
        <button class="oval glass" id="key-combo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
        </button>
      </div>
    </div>
  </div>

  <div id="textbar">
    <button class="tbtn glass" id="text-cancel">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
    </button>
    <input id="text-input" type="text" placeholder="输入…" enterkeyhint="send" autocomplete="off">
    <button class="tbtn primary" id="text-send">发送</button>
  </div>

<script>
  var shiftHold = false;
  var comboPointerId = null;
  var spaceUsed = false;
  var UPPER = { k: "K", j: "J", h: "H", l: "L" };
  var stickyText = false;

  function post(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : null
    }).catch(function () {});
  }
  function sendKey(k) { post("key", { key: k }); }

  function pressDir(key) {
    if (shiftHold) spaceUsed = true;
    sendKey(shiftHold ? UPPER[key] : key);
  }

  document.querySelectorAll(".zone").forEach(function (el) {
    el.addEventListener("pointerdown", function (ev) {
      ev.preventDefault();
      pressDir(el.dataset.key);
    });
  });

  // ── 文本输入（整段发送，支持中文）──
  var textbar = document.getElementById("textbar");
  var textInput = document.getElementById("text-input");

  function openTextBar(sticky) {
    stickyText = !!sticky;
    sendKey(sticky ? "I" : "i");
    textInput.value = "";
    textbar.classList.add("show");
    textInput.focus();
  }
  function closeTextBar() {
    textbar.classList.remove("show");
    textInput.blur();
  }

  async function submitText() {
    await post("text", { text: textInput.value, submit: true });
    if (stickyText) {
      textInput.value = "";
      textInput.focus();
    } else {
      closeTextBar();
    }
  }

  textInput.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") {
      ev.preventDefault();
      submitText();
    }
  });

  document.getElementById("key-i").addEventListener("pointerdown", function (ev) {
    ev.preventDefault();
    if (shiftHold) spaceUsed = true;
    openTextBar(shiftHold);
  });
  document.getElementById("text-send").addEventListener("pointerdown", function (ev) {
    ev.preventDefault();
    submitText();
  });
  document.getElementById("text-cancel").addEventListener("pointerdown", function (ev) {
    ev.preventDefault();
    sendKey("escape");
    closeTextBar();
  });

  // ── 组合键：按住 = shift，松开未配合使用时 = space ──
  var combo = document.getElementById("key-combo");
  combo.addEventListener("pointerdown", function (ev) {
    ev.preventDefault();
    comboPointerId = ev.pointerId;
    shiftHold = true;
    spaceUsed = false;
    combo.classList.add("shift-on");
  });
  function releaseCombo(ev) {
    if (ev.pointerId !== comboPointerId) return;
    comboPointerId = null;
    var wasHold = shiftHold;
    shiftHold = false;
    combo.classList.remove("shift-on");
    if (wasHold && !spaceUsed) sendKey("space");
  }
  document.addEventListener("pointerup", releaseCombo);
  document.addEventListener("pointercancel", function (ev) {
    if (ev.pointerId === comboPointerId) {
      comboPointerId = null;
      shiftHold = false;
      combo.classList.remove("shift-on");
    }
  });

  document.querySelector(".ab.a").addEventListener("pointerdown", function (ev) {
    ev.preventDefault(); sendKey("enter");
  });
  document.querySelector(".ab.b").addEventListener("pointerdown", function (ev) {
    ev.preventDefault(); sendKey("escape");
  });

  document.getElementById("confirm-btn").addEventListener("click", async function () {
    await post("confirm");
    poll();
  });

  function renderRecords(items) {
    var box = document.getElementById("records");
    if (!items || !items.length) {
      box.className = "empty";
      box.textContent = "暂无记录";
      return;
    }
    box.className = "";
    box.innerHTML = items.map(function () {
      return '<div class="item"></div>';
    }).join("");
    var els = box.querySelectorAll(".item");
    els.forEach(function (el, i) { el.textContent = items[i]; });
    box.scrollTop = box.scrollHeight;
  }

  async function poll() {
    try {
      var res = await fetch("status");
      var s = await res.json();
      if (s.state === "connected") {
        document.getElementById("pairing").classList.remove("show");
        document.getElementById("main").classList.add("show");
        document.getElementById("status-text").textContent = "已连接";
        renderRecords(s.records);
      } else {
        document.getElementById("code").textContent = s.code || "----";
        document.getElementById("pairing").classList.add("show");
        document.getElementById("main").classList.remove("show");
      }
    } catch (e) {
      document.getElementById("status-text").textContent = "连接中断";
    }
  }

  poll();
  setInterval(poll, 1000);
</script>
</body>
</html>
"""



