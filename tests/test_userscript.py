#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cx.user.js 离线行为测试（不连学习通，纯本地 mock 播放器）
验证：视频发现 / 倍数锁定 / 静音 / 弹题自动提交 / 播完自动点“下一节” / 后台可见性伪装
运行：  .venv/bin/python tests/test_userscript.py
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = (ROOT / "cx.user.js").read_text(encoding="utf-8")
BODY = re.sub(r"^//\s*==UserScript==.*?//\s*==/UserScript==\s*", "", SRC, flags=re.S)
BODY = BODY.replace("rate: 1.25", "rate: 1.25").replace("tickMs: 1500", "tickMs: 300")

HTML = """
<!doctype html><meta charset="utf-8">
<style>body{margin:0;font:14px sans-serif}.ans-videoquiz{display:none;padding:8px;border:1px solid #ccc}
.opt{padding:4px;cursor:pointer}</style>
<video id="video_html5_api" width="320" height="240"></video>

<div class="ans-videoquiz" id="quiz">
  <div class="ans-videoquiz-title">1. 测试弹题：请选择 A</div>
  <div class="ans-videoquiz-opt" onclick="window.__picks.push('A')">A</div>
  <div class="ans-videoquiz-opt" onclick="window.__picks.push('B')">B</div>
  <button class="ans-videoquiz-submit" onclick="window.__submitted=true">提交</button>
</div>

<a class="next" href="javascript:void 0" onclick="window.__next=(window.__next||0)+1">下一节</a>

<script>
// ---- 用假时间轴驱动真实 <video> 元素，模拟一个有 8 秒时长的视频 ----
window.__picks = []; window.__next = 0; window.__submitted = false;
const v = document.getElementById('video_html5_api');
let fakeT = 0, fakePaused = true;
Object.defineProperty(v, 'duration',  { get: () => 8 });
Object.defineProperty(v, 'paused',    { get: () => fakePaused });
Object.defineProperty(v, 'ended',     { get: () => false });
Object.defineProperty(v, 'currentTime', {
  get: () => fakeT,
  set: x => { fakeT = Math.max(0, x); },
  configurable: true
});
v.play  = () => { fakePaused = false; return Promise.resolve(); };
v.pause = () => { fakePaused = true; };
// 让它“播放”起来
setInterval(() => { if (!fakePaused) fakeT = Math.min(8, fakeT + 0.25); }, 250);
window.__fixtureEnded = () => v.dispatchEvent(new Event('ended'));
window.__showQuiz    = on => { document.getElementById('quiz').style.display = on ? 'block' : 'none'; };
</script>
"""

ok = True


def check(name, cond, extra=""):
    global ok
    print(("  ✔ " if cond else "  ✖ ") + name + ("" if cond else f"  → {extra}"))
    ok = ok and bool(cond)


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"])
        ctx = b.new_context(viewport={"width": 900, "height": 700})
        ctx.add_init_script(BODY)
        page = ctx.new_page()
        page.set_content(HTML)
        page.wait_for_timeout(2500)

        st = page.evaluate("() => window.__CX_STATUS__ || {}")
        print("状态:", st)
        check("找到视频并拿到时长", st.get("d") == 8, st)
        check("自动播放（不再暂停）", st.get("paused") is False, st)
        check("倍数被锁定为 1.25", abs((st.get("rate") or 0) - 1.25) < 0.01, st)
        check("静音生效", page.evaluate("() => document.querySelector('video').muted") is True)

        page.evaluate("() => { document.querySelector('video').playbackRate = 2.0; }")
        page.wait_for_timeout(800)
        check("播放器改回倍数后自动纠正",
              abs(page.evaluate("() => document.querySelector('video').playbackRate") - 1.25) < 0.01)

        page.evaluate("() => window.__showQuiz(true)")
        page.wait_for_timeout(2500)
        picks = page.evaluate("() => window.__picks")
        check("弹题被识别并自动选第一项", picks[:1] == ["A"], picks)
        check("弹题自动提交", page.evaluate("() => window.__submitted") is True)
        page.evaluate("() => window.__showQuiz(false)")

        page.evaluate("() => window.__fixtureEnded()")
        page.wait_for_timeout(4000)
        check("播完自动点下一节", page.evaluate("() => window.__next") >= 1,
              page.evaluate("() => window.__next"))

        check("伪造 visibilityState -> visible",
              page.evaluate("() => document.visibilityState") == "visible")
        check("document.hidden 被改为 false", page.evaluate("() => document.hidden") is False)

        # 日志确认
        logs = page.evaluate("() => window.__CX_LOGS__ || []")
        print(f"\n脚本日志 {len(logs)} 条，最后 5 条：")
        for l in logs[-5:]:
            print("   ", l)

        b.close()

    print("\n结果:", "全部通过" if ok else "有失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
