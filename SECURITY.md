# 安全须知

这个工具会接触到你学习通账号的**登录态**。仓库本身不含任何凭据，但你自己运行时会产生，请按下面的方式保管。

## 会产生凭据的文件

| 路径 | 内容 | 处置 |
|---|---|---|
| `cx_profile/` | Chromium 用户数据目录，内含 `SESSDATA`、`_uid` 等登录 cookie | 只留本地，已在 `.gitignore` |
| `enc_samples.json` | 抓包得到的上报 URL（含 `userid`、`enc`）+ 明文 cookie | 只留本地，已在 `.gitignore` |
| `urls.txt` | 你的真实课程链接（`courseId` / `clazzid` / `enc`） | 只留本地，已在 `.gitignore` |
| `progress.json` | 你的学习进度 | 只留本地，已在 `.gitignore` |

## 提交前自检

```bash
# 1) 应该没有输出（有输出就说明敏感文件被 staged 了）
git ls-files | grep -E 'cx_profile|enc_samples|progress\.json|^urls\.txt$'

# 2) 内容扫描：只应命中本文件的说明文字和过期的登录 URL；出现其它命中就要查
git grep -nIiE 'SESSDATA|_uid=|passport2|cookie:|Bearer |ghp_|github_pat_' -- . ':(exclude)SECURITY.md'

# 3) 确认忽略规则生效（每条都应打印被忽略的路径）
git check-ignore -v --no-index cx_profile/x progress.json enc_samples.json urls.txt .venv/bin/python
```

## 历史里已经混进去了怎么办

```bash
git rm -r --cached cx_profile enc_samples.json progress.json urls.txt
git commit -m "chore: 移除误提交的个人凭据文件"
```

只是从最新 commit 删掉不够——旧 commit 里还留着。彻底清理：

```bash
pip install git-filter-repo
git filter-repo --invert-paths \
  --path cx_profile --path enc_samples.json --path progress.json --path urls.txt
git push --force
```

**已经推到公开仓库的 cookie 视为泄露**，去学习通改密码，旧登录态会失效。

## 推送凭据本身

- PAT 只放在 `git credential` 或环境变量里，不要写进 remote URL：`git remote -v` 不应该出现 `:token@`
- 建议用一次性 URL 推送后立刻清掉：`git remote set-url origin https://github.com/USER/REPO.git`
- 用 SSH 更省事：key 放 `~/.ssh/`，权限 600，不加 passphrase 就别把 key 文件同步到云盘
