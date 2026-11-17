# 机制详解：学习通的视频进度是怎么算的

> 想把工具用好、或者出问题时想自己定位，看这一篇就够了。所有结论都可以用浏览器 F12 现场验证。

## 1. 一条视频从打开到变绿，中间发生了什么

```
打开章节页
   │
   ├─ 页面从服务端拉任务点列表（含 jobid / objectid / duration）
   │
   ├─ 播放器初始化，同一时刻开始周期性上报「我播到第几秒了」
   │     ├─ 上报 1：playingTime=0
   │     ├─ 上报 2：playingTime=15xxx
   │     ├─ 上报 3：playingTime=30xxx
   │     └─ …直到 playingTime 接近 duration
   │
   └─ 服务端把这一串上报累计起来，超过阈值就标记任务点完成
         └─ 页面刷新时任务点显示为绿色 ✔
```

关键点：**完成度是服务端按「上报序列」计算的**，不是页面自己算的。所以：

- 只把 `currentTime` 拖到结尾 → 没有上报序列 → 不会完成
- 上报间隔异常短、增量异常大 → 序列被判无效 → 不会完成
- 中途停止上报超过一定时间 → 这一节可能被重置为未完成

## 2. 上报请求长什么样

```
GET https://mooc1-1.chaoxing.com/multimedia/log/a/{clazzid}/{userid}
    ?clazzid=80000001
    &userid=12345678
    &jobid=work-1234567
    &objectId=0
    &playingTime=45000          ← 已播放量（毫秒）
    &duration=623               ← 视频总时长（秒）
    &d=d_yi
    &msEscaptTime=45000
    &t=1731834245123
    &enc=<32 位 md5>
```

| 字段 | 来源 | 说明 |
|---|---|---|
| `clazzid` | 课程页 URL | 班级 id |
| `userid` | 登录 cookie / 页面变量 | 你的 uid，服务端会和 cookie 比对 |
| `jobid` | 任务点列表 | 这一节视频的任务点 id |
| `objectId` | 任务点列表 | 对象 id，多数课程是 `0` |
| `playingTime` | 播放器 | **已播放毫秒数**，是完成度的核心 |
| `duration` | 播放器 | 总时长，秒；和任务点记录不一致会被判无效 |
| `d` | 固定串 | 通常是 `d_yi` |
| `msEscaptTime` | 播放器 | 毫秒级时间，和 playingTime 基本同步 |
| `t` | 前端 | 当前时间戳 |
| `enc` | 前端 md5 | 见下一节 |

返回值通常是：

```json
{"isPassed": true, "msg": "success"}
```

`isPassed:false` 就意味着这一笔上报被丢弃，进度不涨。

## 3. enc 是什么

`enc` 不是随机串，是前端把若干字段按**固定顺序**拼成一个字符串再做 md5：

```js
// 伪代码，真实顺序以页面 JS 为准
enc = md5(clazzid + '[' + userid + '][' + jobid + '][' + objectId + '][' +
          playingTime_ms + '][' + d + '][' + duration + ']')
```

服务端收到请求后用同样的规则重算一遍，和请求里的 `enc` 比对：

- 一致 → 认为请求是页面发出的，继续校验进度合理性
- 不一致 → 直接丢弃（这就是「自己拼个 URL 发过去没用」的原因）

**怎么拿到真实顺序**：`python3 cx_report.py grab-js --course "URL"`，然后翻 `js_dump/` 里含 `md5` 的文件，找拼串那几行。不同版本的播放器顺序可能不同，改版后要重新挖。

## 4. 服务端还会查什么

| 校验点 | 表现 | 对应处置 |
|---|---|---|
| 增量 vs 真实间隔 | 2x 以上容易失效 | `--rate` 保持 1~1.5 |
| `duration` 与任务点记录一致 | 不一致整条丢弃 | 不要手改 duration |
| `userid` 与 cookie 一致 | 不一致返回未登录 | 用自己账号的 cookie |
| 上报间隔下限 | 一秒发好几次会被判脚本 | `step`/`sleep` 别设太小 |
| 长时间无上报 | 本节进度回退 | 挂机保活 |
| 前台/后台状态 | 切后台可能暂停计时 | `visibility` 伪装 |

## 5. 本项目的策略

因为 `enc` 是前端算的、而且服务端校验「增量 / 间隔」的合理性，**最稳的做法是让页面自己播、自己报**：

- 路线一 / 路线二：只驱动 DOM（`play()`、`playbackRate`、`muted`），上报完全交给页面 → 与真人观看在协议层无差别，只有时间倍率不同
- 路线三：拿到 `enc` 公式后自己构造上报序列 → 省时间，但要自己保证增量和间隔像真的

两条路可以混用：先用路线二正常播，卡住的那几节用路线三补。

## 6. 怎么现场观察

在课程页控制台里：

```js
// 1) 看脚本状态
window.__CX_STATUS__

// 2) 看历史日志
window.__CX_LOGS__

// 3) 看当前播放器
document.querySelector('video')

// 4) 网络面板过滤 multimedia/log，观察上报的频率与 playingTime 增量
```

如果 `__CX_STATUS__` 一直是 `{video:false}`，说明视频不在当前 frame，需要看是哪一层 iframe（F12 → Elements → 逐个 iframe 找 `<video>`）。
