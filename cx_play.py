#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习通（超星）批量刷课 · Playwright 启动器
--------------------------------------------------
原理：把 cx.user.js 作为 init script 注入到每个 frame，
      由脚本自己驱动播放器（真实播放、真实心跳），Playwright 只负责
      起浏览器 / 复用登录态 / 反复打开每个课程的学习页 / 记录进度。

用法：
  1) 首次登录（手动扫码或账密，登录态存进 ./cx_profile）：
       python3 cx_play.py --login
  2) 跑指定课程（课程学习页 URL 从浏览器地址栏复制）：
       python3 cx_play.py --course "https://mooc1-1.chaoxing.com/mycourse/studentstudy?courseId=xxx&clazzid=xxx&enc=xxx"
  3) 一次跑多个课程（每行一个 URL）：
       python3 cx_play.py --list urls.txt
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("缺少依赖：python3 -m pip install playwright && python3 -m playwright install chromium")

HERE = Path(__file__).resolve().parent
PROFILE = HERE / "cx_profile"
PROGRESS = HERE / "progress.json"
USER_JS = HERE / "cx.user.js"

LOGIN_URL = "https://passport2.chaoxing.com/login?fid=&newversion=true&refer=https://i.chaoxing.com"


def load_script(rate=1.25, quiz_mode="auto", debug=True):
    src = USER_JS.read_text(encoding="utf-8")
    # 去掉 UserScript 头（浏览器插件才认，Playwright 不需要）
    body = re.sub(r"^//\s*==UserScript==.*?//\s*==/UserScript==\s*", "", src, flags=re.S)
    # 覆盖配置
    body = body.replace("rate: 1.25", f"rate: {rate}")
    body = body.replace("quizMode: 'auto'", f"quizMode: '{quiz_mode}'")
    body = body.replace("debug: true", f"debug: {'true' if debug else 'false'}")
    return body


def read_progress():
    if PROGRESS.exists():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_progress(d):
    PROGRESS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def status_of(page):
    """从任意 frame 里取播放器状态"""
    best = None
    for fr in page.frames:
        try:
            st = fr.evaluate("() => window.__CX_STATUS__ || null")
        except Exception:
            continue
        if not st:
            continue
        if st.get("d") and st.get("d") > 0:
            best = st
            best["frame"] = fr.url[:120]
    return best


def watch(page, course_url, target_minutes=None, idle_limit=180):
    """打开课程页并盯着播放器，直到视频全都放完或长时间没有任何进度"""
    page.goto(course_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)

    last_t, last_move = -1, time.time()
    started = time.time()
    done_videos = 0

    while True:
        st = status_of(page)
        now = time.time()

        if st and st.get("d"):
            t, d = st.get("t") or 0, st["d"]
            pct = 100 * t / d if d else 0
            print(f"\r  ▶ {pct:5.1f}%  {t:7.1f}/{d:7.1f}s  rate={st.get('rate')}  quiz={st.get('quiz')}   ", end="", flush=True)
            if t > last_t + 0.5:
                last_t, last_move = t, now
            if d and d - t < 2:
                done_videos += 1
                print(f"\n  ✔ 第 {done_videos} 个视频播放完毕")
                last_t, last_move = -1, now
                page.wait_for_timeout(4000)
        else:
            print(f"\r  … 等待播放器（当前 {page.url[:80]}）          ", end="", flush=True)

        if target_minutes and (now - started) / 60 > target_minutes:
            print("\n  达到设定时长，停止")
            return

        if now - last_move > idle_limit:
            print(f"\n  ⚠ 连续 {idle_limit}s 无播放进度，判定本节已结束或需要人工处理，切换下一个任务点")
            return


def click_next_chapter(page):
    """在顶层 frame 尝试点“下一节”"""
    js = """() => {
      const sels = ['.next','.nodeItem.next','[onclick*="nextNode"]',
                    '[onclick*="nextChapter"]','a.nextChapter'];
      for (const s of sels) {
        const el = document.querySelector(s);
        if (el && el.offsetParent !== null) { el.click(); return s; }
      }
      const links = [...document.querySelectorAll('a,p,li,div')]
        .filter(e => e.offsetParent !== null && /^(下一节|下一章|下一关)/.test((e.innerText||'').trim()));
      if (links.length) { links[0].click(); return 'text:' + links[0].innerText.trim(); }
      return false;
    }"""
    try:
        return page.evaluate(js)
    except Exception:
        return False


def run(args):
    PROFILE.mkdir(parents=True, exist_ok=True)
    script = load_script(args.rate, args.quiz, not args.quiet)
    prog = read_progress()

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            headless=False,
            channel=args.channel or None,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
                f"--window-size=1280,900",
            ],
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        ctx.add_init_script(script)          # 每个 frame 都注入
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if args.login:
            page.goto(LOGIN_URL)
            print("→ 请在弹出的浏览器里完成登录（扫码/账密），完成后回到终端按 Enter")
            input()
            print("登录态已保存到", PROFILE)
            ctx.close()
            return

        urls = []
        if args.list:
            urls = [l.strip() for l in Path(args.list).read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.startswith("#")]
        if args.course:
            urls.append(args.course)
        if not urls:
            sys.exit("请用 --course URL 或 --list urls.txt 指定课程")

        for i, u in enumerate(urls, 1):
            key = re.sub(r"[?&](enc|t)=[^&]*", "", u)
            if prog.get(key, {}).get("finished"):
                print(f"[{i}/{len(urls)}] 跳过（已标记完成）：{key[:90]}")
                continue
            print(f"\n[{i}/{len(urls)}] 开始：{key[:110]}")
            try:
                for rnd in range(args.max_rounds):
                    watch(page, u, args.minutes)
                    moved = click_next_chapter(page)
                    print(f"\n  第 {rnd+1} 轮结束，切换下一个任务点 → {moved}")
                    page.wait_for_timeout(4000)
                    if not moved:
                        break
                prog[key] = {"finished": True, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
                save_progress(prog)
            except KeyboardInterrupt:
                print("\n手动中断，进度已保存")
                save_progress(prog)
                break
            except Exception as e:
                print(f"\n  ✖ 出错：{e}")
                prog[key] = {"error": str(e)[:200], "at": time.strftime("%Y-%m-%d %H:%M:%S")}
                save_progress(prog)

        print("\n全部任务结束。剩余章节请查看页面上的任务点颜色（绿色=已完成）")
        if not args.keep_open:
            ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true", help="只做登录，保存登录态")
    ap.add_argument("--course", help="课程学习页 URL")
    ap.add_argument("--list", help="URL 列表文件")
    ap.add_argument("--rate", type=float, default=1.25, help="播放倍数，建议 1~1.5")
    ap.add_argument("--quiz", choices=["auto", "pause"], default="auto", help="弹题处理策略")
    ap.add_argument("--minutes", type=float, default=None, help="单个课程最多跑多少分钟")
    ap.add_argument("--max-rounds", type=int, default=200, help="最多切换多少个任务点")
    ap.add_argument("--channel", default="", help="使用本机 Chrome：--channel chrome")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--keep-open", action="store_true")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
