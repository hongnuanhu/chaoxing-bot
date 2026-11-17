#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习通 视频进度上报（接口直发）骨架 + enc 生成规则提取工具
------------------------------------------------------------------
两条路：
  A. 保真流（推荐）：cx_play.py，页面自己算 enc、自己发心跳，你只管播放。
  B. 直发流：本文件。省流量、能补看，但必须拿到 enc 的拼接公式，
     因为服务端会校验 enc = md5(按课程/任务点/播放毫秒/时间戳拼的串)，
     拼错一个字就返回 {"isPassed":false}。

步骤：
  1) 采集真实上报样本（顺带把公式里的字段全抓下来）
       python3 cx_report.py probe --course "课程学习页URL"
     产出 enc_samples.json：每条 URL 的 query 参数 + 你的 cookie
  2) 从页面 JS 里挖出 enc 拼接顺序
       python3 cx_report.py grab-js --course "课程学习页URL"
     产出 js_dump/*.js 并在终端打印可疑行（含 enc / md5 / playingTime）
  3) 把公式填进 enc_spec.json 的 template，然后跑
       python3 cx_report.py run --spec enc_spec.json
"""
import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode

try:
    import requests
except ImportError:
    sys.exit("缺少依赖：python3 -m pip install requests")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

HERE = Path(__file__).resolve().parent
PROFILE = HERE / "cx_profile"
SAMPLES = HERE / "enc_samples.json"
SPEC = HERE / "enc_spec.json"
JSDIR = HERE / "js_dump"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 服务端真正校验的就是这个串，顺序随版本变，务必用 grab-js 确认真实顺序
DEFAULT_TEMPLATE = "{clazzid}[{userid}][{jobid}][{objectid}][{playing_ms}][{d}][{duration}]"


# --------------------------------------------------------------------------
# enc
# --------------------------------------------------------------------------
def md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def gen_enc(template: str, **kw) -> str:
    """template 里的占位符用 kw 填充后做 md5；{playing_ms} = 播放进度毫秒"""
    kw.setdefault("playing_ms", int(float(kw.get("playing_time", 0)) * 1000))
    kw.setdefault("d", "d_yi")
    return md5(template.format(**kw))


# --------------------------------------------------------------------------
# 1. 采集真实样本：拦 XHR / fetch 里的 multimedia/log
# --------------------------------------------------------------------------
PROBE_JS = r"""
(() => {
  window.__CX_SAMPLES__ = window.__CX_SAMPLES__ || [];
  const hit = u => typeof u === 'string' && u.indexOf('/multimedia/log') > -1;
  const push = u => { if (hit(u)) window.__CX_SAMPLES__.push(u); };

  const ox = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (m, u) { push(u); return ox.apply(this, arguments); };

  if (window.fetch) {
    const of = window.fetch;
    window.fetch = function (input) {
      try { push(typeof input === 'string' ? input : (input && input.url)); } catch (e) {}
      return of.apply(this, arguments);
    };
  }
  if (navigator.sendBeacon) {
    const ob = navigator.sendBeacon.bind(navigator);
    navigator.sendBeacon = function (u, d) { push(u); return ob(u, d); };
  }
})();
"""


def probe(course_url, seconds=180):
    if sync_playwright is None:
        sys.exit("probe 需要 playwright")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), headless=False,
            args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"],
            locale="zh-CN", timezone_id="Asia/Shanghai")
        ctx.add_init_script(PROBE_JS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(course_url, wait_until="domcontentloaded")
        print(f"→ 浏览器已打开，保持播放 {seconds}s 以采集上报流量…（视频需已开始播放）")
        for i in range(seconds // 10):
            page.wait_for_timeout(10000)
            for fr in page.frames:
                try:
                    fr.evaluate("() => { const v=document.querySelector('video'); if(v&&v.paused){v.muted=true;v.play();} }")
                except Exception:
                    pass
            n = sum(len(fr.evaluate("() => window.__CX_SAMPLES__ || []") or []) for fr in page.frames
                    if fr.url.startswith("http"))
            print(f"\r  已采集 {n} 条上报请求  {i*10}s", end="", flush=True)

        samples, cookies = [], []
        for fr in page.frames:
            if not fr.url.startswith("http"):
                continue
            try:
                samples += fr.evaluate("() => window.__CX_SAMPLES__ || []") or []
            except Exception:
                pass
        cookies = [{"name": c["name"], "value": c["value"], "domain": c["domain"]}
                   for c in ctx.cookies()]
        ctx.close()

    seen, rows = set(), []
    for u in samples:
        if u in seen:
            continue
        seen.add(u)
        q = parse_qs(urlparse(u).query)
        rows.append({"url": u, "path": urlparse(u).path,
                     "query": {k: v[0] for k, v in q.items()}})
    out = {"captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "cookie": cookies, "samples": rows}
    SAMPLES.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ 写入 {SAMPLES}（{len(rows)} 条）")
    if rows:
        s = rows[-1]
        print("\n最后一条样本的字段：")
        for k, v in s["query"].items():
            print(f"   {k:20s} = {v}")
        print(f"\n   → enc = {s['query'].get('enc')}")
        print("   → 拿这些字段和页面 JS 里的拼接顺序对照，填进 enc_spec.json")


# --------------------------------------------------------------------------
# 2. 挖 enc 公式
# --------------------------------------------------------------------------
INTEREST = re.compile(r"(enc\s*[:=]|md5|playingTime|multimedia/log|msEscaptTime|jobid)", re.I)


def grab_js(course_url):
    if sync_playwright is None:
        sys.exit("grab-js 需要 playwright")
    JSDIR.mkdir(exist_ok=True)
    urls = set()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(user_data_dir=str(PROFILE), headless=False,
                                                  locale="zh-CN")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(course_url, wait_until="domcontentloaded")
        page.wait_for_timeout(12000)
        for fr in page.frames:
            if not fr.url.startswith("http"):
                continue
            try:
                srcs = fr.evaluate("() => [...document.scripts].map(s => s.src).filter(Boolean)")
                urls |= set(srcs)
            except Exception:
                pass
        cookie_hdr = "; ".join(f'{c["name"]}={c["value"]}' for c in ctx.cookies())
        ctx.close()

    print(f"发现 {len(urls)} 个脚本，开始下载…")
    sess = requests.Session()
    for u in sorted(urls):
        host = urlparse(u).netloc
        try:
            r = sess.get(u, headers={"User-Agent": UA, "Cookie": cookie_hdr,
                                     "Referer": course_url}, timeout=15)
            name = re.sub(r"[^\w.\-]", "_", host + "_" + urlparse(u).path.split("/")[-1])[:120]
            f = JSDIR / (name or f"js_{abs(hash(u))}.js")
            f.write_text(r.text, encoding="utf-8", errors="ignore")
        except Exception as e:
            print("  skip", u, e)

    print("\n可疑代码行：")
    for f in sorted(JSDIR.glob("*.js")):
        txt = f.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(txt.splitlines(), 1):
            if INTEREST.search(line) and ("md5" in line.lower() or "enc" in line.lower()):
                print(f"{f.name}:{i}: {line.strip()[:220]}")


# --------------------------------------------------------------------------
# 3. 直发上报
# --------------------------------------------------------------------------
REPORT_PATH = "/multimedia/log/a/{clazzid}/{userid}"
LOGIN = "https://mooc1-1.chaoxing.com"


def send_report(spec, sample, cookie_hdr, playing_time, duration, step=60, sleep=1.0,
                clazzid=None, userid=None, jobid=None, objectid=None, dry=False):
    sid = sample["query"].get("_jobid") or sample["query"].get("jobid") or jobid
    oid = sample["query"].get("objectId") or objectid
    cid = clazzid or sample["query"].get("clazzId") or sample["query"].get("clazzid")
    uid = userid or sample["query"].get("userid") or sample["query"].get("uid")
    d = sample["query"].get("d", "d_yi")
    template = spec.get("template", DEFAULT_TEMPLATE)

    host = "https://" + urlparse(sample["url"]).netloc
    path = sample["path"]
    fixed = {k: v for k, v in sample["query"].items()
             if k not in ("playingTime", "enc", "msEscaptTime", "t", "_t", "playing_time")}

    s = requests.Session()
    hdr = {"User-Agent": UA, "Referer": spec.get("referer", LOGIN),
           "X-Requested-With": "XMLHttpRequest", "Cookie": cookie_hdr}

    t = 0.0
    while t <= duration:
        pt = min(t, duration)
        params = dict(fixed)
        params["playingTime"] = int(pt * 1000) if spec.get("playing_unit") == "ms" else int(pt)
        params["duration"] = int(duration)
        params["msEscaptTime"] = int(pt * 1000)
        params["t"] = int(time.time() * 1000)
        params["enc"] = gen_enc(template,
                                clazzid=cid, userid=uid, jobid=sid, objectid=oid,
                                playing_time=pt, playing_ms=int(pt * 1000),
                                duration=int(duration), d=d, t=params["t"])
        url = f"{host}{path}?{urlencode(params)}"
        if dry:
            print("[dry]", url[:200])
        else:
            try:
                r = s.get(url, headers=hdr, timeout=15)
                print(f"  {pt:7.1f}s/{duration:.0f}s → {r.status_code} {r.text[:120]}")
                if r.status_code == 403 or '"isPassed":false' in r.text:
                    print("  ⚠ 被拒：优先检查 enc 公式 / playingTime 单位 / cookie 是否过期")
            except Exception as e:
                print("  x", e)
        t += step
        time.sleep(sleep)


def run(spec_path):
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    data = json.loads(SAMPLES.read_text(encoding="utf-8"))
    if not data["samples"]:
        sys.exit("enc_samples.json 里没有样本，先跑 probe")
    cookie_hdr = "; ".join(f'{c["name"]}={c["value"]}' for c in data["cookie"])
    for task in spec["tasks"]:
        sample = data["samples"][task.get("sample_index", -1)]
        print(f"\n▶ 任务 {task.get('jobid')} duration={task['duration']}")
        send_report(spec, sample, cookie_hdr,
                    playing_time=0, duration=task["duration"],
                    step=task.get("step", 60), sleep=task.get("sleep", 1.0),
                    clazzid=task.get("clazzid"), userid=task.get("userid"),
                    jobid=task.get("jobid"), objectid=task.get("objectid"),
                    dry=spec.get("dry", False))


def make_spec():
    if SPEC.exists():
        print("已存在", SPEC)
        return
    SPEC.write_text(json.dumps({
        "template": DEFAULT_TEMPLATE,
        "playing_unit": "s",
        "referer": "https://mooc1-1.chaoxing.com/",
        "dry": True,
        "tasks": [
            {"jobid": "JOB_ID", "objectid": "OBJECT_ID", "clazzid": "CLAZZ_ID",
             "userid": "USER_ID", "duration": 600, "step": 60, "sleep": 1.0}
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已生成模板", SPEC, "→ 填好 template 和 tasks 再 run")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["probe", "grab-js", "run", "init-spec"])
    ap.add_argument("--course", help="课程学习页 URL")
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--seconds", type=int, default=180)
    a = ap.parse_args()
    if a.mode == "probe":
        probe(a.course, a.seconds)
    elif a.mode == "grab-js":
        grab_js(a.course)
    elif a.mode == "run":
        run(a.spec)
    else:
        make_spec()
