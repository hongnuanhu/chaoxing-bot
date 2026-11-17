// ==UserScript==
// @name         超星学习通 自动刷课助手
// @namespace    local.cx.bot
// @version      1.3.0
// @description  视频自动播放 / 静音 / 倍数 / 弹题处理 / 自动下一节 / 挂机保活 / 进度日志
// @author       local
// @match        *://*.chaoxing.com/*
// @match        *://*.chaoxing.cn/*
// @match        *://*.cldisk.com/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

/* 在每一个 frame 里都会执行（Tampermonkey 默认注入所有匹配 frame）。
   播放器在三级 iframe 里，所以不要加 @noframes。*/

(function () {
  'use strict';
  if (window.__CX_BOT__) return;
  window.__CX_BOT__ = true;

  const CFG = {
    rate: 1.25,          // 播放倍数；不建议 >1.5，学习通有心跳间隔校验
    mute: true,          // 静音（防止多标签同时出声）
    autoNext: true,      // 视频结束后自动下一节/下一个任务点
    quizMode: 'auto',    // 'auto'=弹题自动作答并继续, 'pause'=弹题就暂停等你人工答
    quizPick: 0,         // 弹题默认选第几个（0=第一个）
    keepAlive: true,     // 定时微调 currentTime，防止挂在后台被判超时
    keepAliveMs: 30000,  // 保活间隔
    tickMs: 1500,        // 主循环轮询间隔
    debug: true,
  };

  const LOG_KEY = 'cx_bot_log';
  window.__CX_LOGS__ = [];
  const log = (...a) => {
    const line = `[CX ${new Date().toLocaleTimeString()}] ${a.join(' ')}`;
    if (CFG.debug) console.log(line);
    window.__CX_LOGS__.push(line);
    if (window.__CX_LOGS__.length > 500) window.__CX_LOGS__.shift();
    try {
      const arr = JSON.parse(localStorage.getItem(LOG_KEY) || '[]');
      arr.push(line);
      localStorage.setItem(LOG_KEY, JSON.stringify(arr.slice(-300)));
    } catch (e) {}
  };

  /* ---------------- 视频元素定位 ---------------- */
  function findVideo() {
    const sels = [
      'video.vjs-tech',
      '#video_html5_api',
      '.vjs-tech',
      'video',
      '#videoContent video',
      '.ans-video video',
    ];
    for (const s of sels) {
      const el = document.querySelector(s);
      if (el && el.tagName === 'VIDEO') return el;
    }
    return null;
  }

  /* ---------------- 事件伪装：防止"切后台/失焦"判定 ---------------- */
  function patchVisibility() {
    try {
      Object.defineProperty(document, 'hidden', { get: () => false, configurable: true });
      Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
      document.addEventListener('visibilitychange', e => e.stopImmediatePropagation(), true);
      window.addEventListener('blur', e => e.stopImmediatePropagation(), true);
    } catch (e) {}
  }

  /* ---------------- 播放器接管 ---------------- */
  let curVideo = null;

  function hookVideo(v) {
    if (!v || v === curVideo) return;
    curVideo = v;
    log('找到视频, duration=', v.duration);

    // 倍数锁定（播放器会把自己的速率写回去，这里持续纠正）
    v.addEventListener('ratechange', () => {
      if (Math.abs(v.playbackRate - CFG.rate) > 0.01) v.playbackRate = CFG.rate;
    });
    v.playbackRate = CFG.rate;
    v.muted = CFG.mute;
    v.volume = CFG.mute ? 0 : 1;

    // 拖动进度条绕过检测
    v.addEventListener('seeking', () => {
      if (v.__cxSeekSelf) return;
      log('检测到 seek 事件 →', Math.round(v.currentTime));
    }, true);

    // 播放中断自动恢复
    v.addEventListener('pause', () => {
      if (v.ended) return;
      if (quizVisible()) return;   // 弹题导致的暂停不抢
      setTimeout(() => { try { v.play(); } catch (e) {} }, 800);
    });
    v.addEventListener('ended', onEnded);
    try { v.play(); } catch (e) {}
  }

  /* ---------------- 弹题处理 ---------------- */
  function quizBox() {
    const sels = [
      '.ans-videoquiz', '.videoquiz', '#videoquiz',
      '.ans-videoquiz-box', '[class*="videoquiz"]',
      '.ans-job-icon-question',
    ];
    for (const s of sels) {
      const el = document.querySelector(s);
      if (el && el.offsetParent !== null) return el;
    }
    return null;
  }
  const quizVisible = () => !!quizBox();

  function handleQuiz() {
    const box = quizBox();
    if (!box) return false;

    const qText = (box.querySelector('.ans-videoquiz-title, .title, p') || {}).innerText || '(未知题目)';
    const opts = [...box.querySelectorAll('.ans-videoquiz-opt, .opt, li')]
      .filter(o => o.offsetParent !== null);

    if (CFG.quizMode === 'pause') {
      log('【人工介入】弹题:', qText.trim().slice(0, 60));
      return true;
    }

    log('【自动答】弹题:', qText.trim().slice(0, 60), ' 选项数=', opts.length);
    if (opts.length) {
      const pick = opts[Math.min(CFG.quizPick, opts.length - 1)];
      pick.click();
      const submit = box.querySelector('.ans-videoquiz-submit, .submit, button');
      if (submit) submit.click();
      log('已提交答案:', pick.innerText.trim().slice(0, 30));
    }
    // 弹题面板有时需要点关闭才继续
    setTimeout(() => {
      const close = document.querySelector('.ans-videoquiz-close, .popup-close, .mask-close');
      if (close) close.click();
      const v = findVideo();
      if (v) { try { v.play(); } catch (e) {} }
    }, 1200);
    return true;
  }

  /* ---------------- 自动下一节 / 下一个任务点 ---------------- */
  const NEXT_SELS = [
    '.next', '.nextNode', '.nodeItem.next',
    'a:has-text("下一节")', 'a:has-text("下一章")',
    '[onclick*="nextNode"]', '[onclick*="nextChapter"]',
    '.orientation p:last-child',
  ];

  function clickNext() {
    // 1) 章节页的"下一节"
    for (const s of NEXT_SELS) {
      let el = null;
      try { el = document.querySelector(s); } catch (e) { el = null; }
      if (el && el.offsetParent !== null) {
        log('点击下一节:', s);
        el.click();
        return true;
      }
    }
    // 2) 章节列表里找未完成的红色/未打勾任务点
    const tasks = [...document.querySelectorAll(
      '[class*="task_point"], .ans-job-icon, .catalog_points li, .chapter_item a'
    )].filter(t => t.offsetParent !== null && !/done|complete|finish|✔|job-finish/i.test(t.className));
    const target = tasks.find(t => /video|音频|文档|章节测验|未完成|unfinish/i.test(t.className + t.innerText));
    if (target) {
      log('跳转未完成任务点:', (target.innerText || target.className).trim().slice(0, 40));
      target.click();
      return true;
    }
    log('没有找到下一节，可能已到本章末尾');
    return false;
  }

  function onEnded() {
    const v = findVideo();
    const now = Date.now();
    if (v) {
      if (v.__cxEndedAt && now - v.__cxEndedAt < 15000) return; // 15s 冷却，避免重复点下一节
      v.__cxEndedAt = now;
    }
    log('视频播放结束');
    if (!CFG.autoNext) return;
    setTimeout(clickNext, 2500);
  }

  /* ---------------- 挂机保活 ---------------- */
  let ka = null;
  function startKeepAlive() {
    if (ka) return;
    ka = setInterval(() => {
      const v = findVideo();
      if (!v || v.paused) return;
      // 轻微回拨再前进，让 currentTime 持续变化但进度不倒退
      try {
        if (v.currentTime > 0.5) v.currentTime = v.currentTime - 0.3;
      } catch (e) {}
      log('keepalive t=', Math.round(v.currentTime), '/', Math.round(v.duration || 0));
    }, CFG.keepAliveMs);
  }

  /* ---------------- 主循环 ---------------- */
  function tick() {
    if (handleQuiz()) return;

    const v = findVideo();
    if (v) {
      hookVideo(v);
      if (v.paused && !v.ended && !quizVisible()) {
        try { v.play(); } catch (e) {}
      }
      if (Math.abs(v.playbackRate - CFG.rate) > 0.01) v.playbackRate = CFG.rate;
      v.muted = CFG.mute;
      // 完成判定：接近末尾且不是直播
      if (v.duration && isFinite(v.duration) && v.duration - v.currentTime < 1.2 && v.currentTime > 1) {
        onEnded();
      }
    }
    // 暴露状态给外部脚本（Playwright 读这个）
    window.__CX_STATUS__ = v
      ? { t: v.currentTime, d: v.duration, paused: v.paused, rate: v.playbackRate, quiz: quizVisible() }
      : { video: false, url: location.href };
  }

  patchVisibility();
  setInterval(tick, CFG.tickMs);
  if (CFG.keepAlive) startKeepAlive();
  log('bot ready @', location.href);
})();
