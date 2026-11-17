# chaoxing-bot · 学习通（超星）自动播放助手

[![ci](https://github.com/hongnuanhu/chaoxing-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/hongnuanhu/chaoxing-bot/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

驱动学习通网页播放器自动播完视频任务点：自动播放、倍数锁定、静音、弹题自动作答、播完自动下一节、挂机保活。
附带一条「直发进度上报」的进阶路线，方便补看或省带宽。

> 仅供学习自动化技术、以及在自己账号上处理自己已选课程。仓库不含任何账号凭据，运行后产生的登录态请留在本地，见 [SECURITY.md](SECURITY.md)。

---

## 目录

```
.
├── cx.user.js              # 核心：Tampermonkey 用户脚本 / 也可被 Playwright 注入
├── cx_play.py              # 启动器：起浏览器、复用登录态、打开课程、盯进度、切任务点
├── cx_report.py            # 进阶：直发进度上报（含 enc 公式提取工具）
├── run.sh                  # 统一入口（自动用本地 venv）
├── enc_spec.json           # 直发路线配置模板
├── urls.txt.example        # 批量课程 URL 列表格式
├── tests/test_userscript.py# 离线行为测试（本地 mock 播放器，10 项断言）
├── SECURITY.md             # 凭据处置与提交前自检
└── .github/workflows/ci.yml# 语法检查 + 行为测试
```

## 安装

```bash
git clone https://github.com/hongnuanhu/chaoxing-bot.git chaoxing-bot
cd chaoxing-bot

python3 -m venv .venv
.venv/bin/pip install playwright requests
.venv/bin/python -m playwright install chromium
chmod +x run.sh
```

验证环境（不需要账号，纯本地 mock）：

```bash
.venv/bin/python tests/test_userscript.py
```

## 一、主路线：让真播放器自己跑（推荐）

学习通的视频进度由播放器**自己**按心跳上报：
`/multimedia/log/a/{clazzid}/{userid}?...&enc=md5(拼串)`，
`enc` 由前端按「班级 id + 用户 id + 任务点 id + 对象 id + 播放毫秒 + 时间戳 + 时长」拼串做 md5。

所以最稳的做法不是伪造请求，而是**把页面驱动起来、让 enc 由页面自己算**——`cx_play.py` 干的就是这件事。

```bash
# 1) 首次登录：弹出真浏览器，扫码或账密登录，登录态存进 ./cx_profile
./run.sh cx_play.py --login

# 2) 课程链接：浏览器打开「我学的课 → 某门课」，复制地址栏
#    https://mooc1-1.chaoxing.com/mycourse/studentstudy?courseId=xxx&clazzid=xxx&enc=xxx

# 3) 开跑
./run.sh cx_play.py --course "上面那条URL" --rate 1.25 --quiz auto
```

终端实时输出：

```
▶  42.7%    256.3/600.0s  rate=1.25  quiz=False
✔ 第 1 个视频播放完毕
第 3 轮结束，切换下一个任务点 → .next
```

一个课程跑完自动切章节；全部结束写入 `progress.json`，下次自动跳过。
批量：`cp urls.txt.example urls.txt`（填 URL）→ `./run.sh cx_play.py --list urls.txt`。

### 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--rate` | 1.25 | 播放倍数。超过 1.5 容易被判异常（平台比对上报增量与真实时间间隔） |
| `--quiz` | auto | 弹题策略：`auto` 自动选第一项并提交；`pause` 暂停等人工答 |
| `--minutes` | 无 | 单课程最长运行分钟数 |
| `--max-rounds` | 200 | 最多切换多少个任务点 |
| `--channel chrome` | 空 | 用本机 Chrome（指纹更像真人）而不是内置 Chromium |
| `--keep-open` | 关 | 跑完不关浏览器，便于人工检查 |

### 脚本内部行为（改 `cx.user.js` 顶部 CFG 生效）

1. **视频发现**：`video.vjs-tech` / `#video_html5_api` / `video`，注入所有 frame，多层 iframe 都能命中
2. **倍数锁定**：监听 `ratechange`，播放器改回去就立刻纠正
3. **静音**：`muted=true, volume=0`
4. **中断自愈**：`pause` 后 800ms 自动 `play()`；弹题导致的暂停不抢
5. **弹题处理**：识别 `.ans-videoquiz` / `[class*=videoquiz]`，自动选 + 提交 + 关面板，题目文本记入日志
6. **挂机保活**：每 30s 轻微回拨 `currentTime`，保证持续有 `timeupdate`
7. **后台伪装**：`document.hidden` / `visibilityState` 固定可见，吞掉 `visibilitychange` / `blur`
8. **自动下一节**：`.next` / `[onclick*=nextNode]` / 「下一节」文字 / 未完成任务点，15s 冷却防连点

---

## 二、进阶：直发进度上报

只在你已经能从页面拿到 `enc` 拼接公式时使用。

```bash
# 1) 采集真实样本（开播放器跑 3 分钟，拦 XHR / fetch / beacon）
./run.sh cx_report.py probe --course "课程URL" --seconds 180
#    → enc_samples.json：完整 query 字段 + 当前 cookie（勿提交）

# 2) 从页面 JS 挖 enc 拼接顺序
./run.sh cx_report.py grab-js --course "课程URL"
#    → js_dump/*.js，终端打印含 enc / md5 / playingTime 的可疑行

# 3) 把公式填进 enc_spec.json（占位符：{clazzid} {userid} {jobid} {objectid}
#    {playing_ms} {d} {duration} {t}），先 dry=true 看一眼生成的 URL

# 4) 发送
./run.sh cx_report.py run --spec enc_spec.json
```

返回 `{"isPassed":true}` 即成功；`false` 说明 `enc` 串拼错（顺序 / 单位 / 是否乘 1000）、
`playingTime` 单位不符，或 cookie 过期（重跑 `--login`）。

| 参数 | 含义 |
|---|---|
| `jobid` / `_jobid` | 任务点 id |
| `objectId` | 视频对象 id |
| `clazzid` / `userid` | 班级 id、用户 uid |
| `playingTime` | 已播放量（秒或毫秒，由 `enc_spec.json` 的 `playing_unit` 决定） |
| `duration` | 视频总时长（秒） |
| `d` | 固定串，通常 `d_yi` |
| `msEscaptTime` | 毫秒级时间 |
| `enc` | 上述拼串的 md5 |

---

## 三、平台侧检测与对策

| 检测点 | 现象 | 对策 |
|---|---|---|
| 上报增量 / 间隔比对 | 2x 以上或瞬间跳进度 → 本节不计 | `--rate` 保持 1~1.5 |
| `seeking` 拖动检测 | 进度条置灰 | 脚本不拖进度，只自然播放 |
| 长时间无 `timeupdate` | 判挂机超时 | 保活回拨（内置） |
| 切后台暂停 | 视频停住 | visibility 伪装（内置） |
| 弹题不答 | 卡住不前进 | `--quiz auto` / `pause` |
| 多端并发登录 | 登录态失效、进度清零 | 单账号单浏览器，`--list` 串行 |
| 任务点不变绿 | 上报被拒 | 先 `probe` 比对样本的 `duration` / `playingTime` |

## 四、排查

| 症状 | 处理 |
|---|---|
| 卡在登录页 | 登录态过期：重跑 `--login`，或删 `cx_profile/` 重登 |
| 一直 `… 等待播放器` | 音频 / 文档任务点，或播放器在更深的 iframe：`--keep-open` 看 frame URL |
| 视频不动 | 该节有前置条件（章节测验 / 讨论），先手动处理；或 `--quiz pause` 看是否在等弹题 |
| 弹题答错扣分 | 改 `--quiz pause` 人工作答，或把题库答案写进 `handleQuiz` |
| 进度条不动但日志在涨 | 旧版播放器（`ans.Drag`）：把 `rate` 改 1.0 再试 |
| 想用 Tampermonkey | 直接安装 `cx.user.js`，效果等同，只是要手动点课 |

## 五、测试

```bash
.venv/bin/python tests/test_userscript.py
```

本地 mock 一个 8 秒播放器，验证：视频发现、倍数锁定、静音、改回倍数自愈、弹题自动提交、播完点下一节、visibility 伪装。

## License

[MIT](LICENSE)
