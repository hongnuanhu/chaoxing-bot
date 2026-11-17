# 排查手册

按症状查。每条都给「判断依据 + 处置」，不靠猜。

---

## A. 脚本没反应

### A1. 控制台里没有 `[CX …]` 字样

判断：脚本根本没注入。

依次确认：
1. Tampermonkey 图标上有没有数字？没有 → 脚本没装成功，重装 `cx.user.js`
2. 扩展详情 → 站点访问权限 → 是否允许 `*.chaoxing.com`（Chrome 的「仅点击时运行」会导致不注入）
3. 控制台切到正确的 frame：F12 → Console 左上角的下拉框，视频通常在 `mooc1-1.chaoxing.com` 或 `ananas/modules/video/` 那一层
4. 试试 `window.__CX_BOT__` —— 返回 `true` 说明注入过

### A2. 有日志但视频不播

```js
window.__CX_STATUS__
```

- `{video:false}` → 视频不在这层 frame，见 A3
- `{t:0, d:NaN}` → `src` 没加载，网络或权限问题
- `paused:true` 且 `quiz:false` → 被浏览器自动播放策略拦了。在地址栏给站点开「允许声音自动播放」，或用路线二（Playwright 带 `--autoplay-policy` 参数）

### A3. 找不到视频元素

F12 → Elements → 搜 `<video`。如果搜得到但脚本没接管，说明它在跨域 iframe 里（用户脚本默认会注入所有匹配 frame，但 `@match` 必须覆盖）。

手动看一眼所有 frame 的 URL：

```js
// 在顶层控制台执行
[...document.querySelectorAll('iframe')].map(f => f.src)
```

把视频所在的域名加进 `@match`（例如 `*://*.chaoxing.com/*` 已经覆盖，但 `*.cldisk.com` 之类要单独加）。

---

## B. 播了但不计进度

这是最常见的「白跑」情形。判定顺序如下。

### B1. 先确认上报有没有发出

F12 → Network → 过滤 `multimedia/log`。

- **一条都没有** → 播放器没在真播（看 A2），或这一节根本不是视频任务点
- **有请求但返回 `isPassed:false`** → 服务端拒收，看 B2
- **返回 `isPassed:true` 但任务点不绿** → 说明累计没到阈值，或这一节还有别的任务点没做（章节测验/讨论），看 B3

### B2. 被拒的常见原因

| 现象 | 原因 | 处置 |
|---|---|---|
| 增量 / 间隔不匹配 | 倍速过高 | `--rate 1.0` 重跑这一节 |
| `duration` 不一致 | 手动改过或版本差异 | 别改 duration，用 `probe` 抓真实值对照 |
| 请求很密（一秒多条） | `sleep` 太小 | `sleep` ≥ 1.0 |
| 401 / 未登录 | cookie 过期 | 重跑 `--login` |
| `enc` 校验失败 | 拼串顺序/单位错 | 重新 `grab-js` 挖公式 |

### B3. 进度涨了但不变绿

任务点变绿的条件通常不止「看完视频」：

- 本章有章节测验没做 → 先做测验
- 有讨论帖要求 → 回一条
- 有文档 / PPT 任务点没翻完 → 逐个点开

判断方法：章节列表里每个任务点图标颜色不同，红色/灰色 = 未完成。把鼠标悬停能看到未完成的具体项。

---

## C. 卡在某一节不动

### C1. 一直弹题

说明 `quizMode:'auto'` 答错了、或者弹题面板结构变了没被识别。

临时处置：`--quiz pause`，人工答完让它继续。
长期处置：把题目文本（控制台里有）整理成映射表，改 `cx.user.js` 的 `handleQuiz`，命中就选固定答案。

### C2. 播放到一半停住，日志也不动

```js
window.__CX_STATUS__
```

`t` 不再增长但 `paused:false` → 视频源断了。刷新这一节重来。
`t` 增长到某个值就回退 → 服务端在校验并回退进度，通常是倍速问题，降到 1.0。

### C3. `自动下一节` 点错了地方

日志里看 `点击下一节: <selector>`。如果点到了错误的元素，把那个 selector 从 `NEXT_SELS` 里去掉，或改成你课程实际用的。

---

## D. 环境类问题

| 症状 | 处置 |
|---|---|
| `ModuleNotFoundError: playwright` | 用 `.venv/bin/python` 而不是系统 `python3`；或重跑 `pip install -r requirements.txt` |
| `playwright install` 卡住 | 换镜像或重试；国内网络可设 `PLAYWRIGHT_DOWNLOAD_HOST` |
| `Executable doesn't exist at …/chromium-…` | 内核没装好：`python -m playwright install chromium` |
| macOS 报「无法验证开发者」 | `xattr -cr ~/Library/Caches/ms-playwright` |
| Windows 找不到 `run.cmd` | 用 `run.cmd cx_play.py --login`；或直接 `.venv\Scripts\python.exe cx_play.py --login` |
| 浏览器启动后立刻关闭 | 看终端报错；多数是 `cx_profile/` 被另一个进程占用（上次没退干净，`pkill -f playwright`） |
| 登录二维码刷不出来 | 窗口太小或被挡；`--keep-open` 手动点一下刷新 |

---

## E. 想把现场信息交出来（提 issue 前）

```bash
# 1) 版本信息
.venv/bin/python -c "import playwright,sys;print(sys.version);print(playwright.__version__)"

# 2) 脱敏后的状态（不要贴 cookie！）
#    在课程页控制台执行：
JSON.stringify(window.__CX_STATUS__)
window.__CX_LOGS__.slice(-20)

# 3) 脚本自检结果
.venv/bin/python tests/test_userscript.py
```

**注意**：贴日志前删掉 URL 里的 `enc=`、cookie、`userid`。这些等于你的账号凭据。
