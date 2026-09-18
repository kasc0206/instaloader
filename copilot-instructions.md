# Instaloader 项目 — AI 辅助开发说明

## 项目概述

本项目是基于 [Instaloader](https://github.com/instaloader/instaloader) 的修改版（当前版本 `4.15.3+local1`，基于上游 v4.15.3），用于 Instagram 数据采集和分析。在原版基础上增加了 Instagram API 403 错误的修复、Web API 支持、以及多个自定义分析脚本。

## 目录结构

```
.
├── instaloader/                  # 核心库（修改版）
│   ├── __init__.py               # 包导出，版本号
│   ├── instaloader.py            # 主类 — 下载/管理
│   ├── instaloadercontext.py     # 上下文、API 会话、速率控制
│   ├── structures.py             # 数据结构（Profile, Post, Story 等）
│   ├── nodeiterator.py           # 数据迭代器
│   ├── sectioniterator.py        # 分区迭代器
│   ├── lateststamps.py           # 时间戳管理
│   ├── exceptions.py             # 自定义异常
│   └── __main__.py               # CLI 入口
├── rate_limiter.py               # 统一限速模块（反爬频率规范）
├── import_cookies.py             # 浏览器 Cookie 导入 / 会话生成
├── fetch_all_followers.py        # 粉丝采集器
├── analyze_followers.py          # 粉丝关注关系分析
├── analyze_kasc0206.py           # 批量用户详情采集
├── analyze_mutual.py             # 相互关注用户详情
├── ins_downloader.py             # 通用下载工具
├── verify_downloads.py           # 下载完整性核验（远端帖子 vs 本地文件）
├── download_test/                # 已下载的 Instagram 用户资料
│   ├── chrissylii_/
│   ├── pikapikammmmm/
│   ├── :tagged/                  # （位于各用户目录内）被 @ 的内容
│   ├── _gone_accounts.txt        # 已确认不存在的账号（--update-all 自动跳过）
│   └── ...（共 24 个用户目录）
├── docs/                         # Sphinx 文档
├── deploy/                       # 部署配置
├── test/                         # 单元测试（联网集成测试，见下）
└── .vscode/tasks.json            # 常用任务
```

## 自定义脚本

### `rate_limiter.py` — 统一限速模块（基础设施）

- 把手写 `requests.Session.get()` 的请求纳入与上游 `RateController` 一致的滑动窗口限速
- 按端点分类计数：`other` 75 次/660s、`graphql` 200 次/660s、`iphone` 199 次/1800s
- 429 后递增冷却（60s 起，上限 30 分钟），成功后逐步消除
- 提供 `add_profile_args(parser)` 统一挂载 `--rate-profile` / `--min-interval`
- 参数细节与用法见「🚦 请求频率规范」

### `import_cookies.py` — 浏览器 Cookie 导入 / 会话生成（登录前置步骤）

- **所有需要登录的脚本之前，先跑这一步**
- 从 Edge / Chrome / Firefox 等浏览器读取 `instagram.com` cookies
- 校验登录状态后保存 Instaloader 会话，供后续脚本复用
- 用法：
  ```bash
  python3 import_cookies.py                    # 默认从 Edge 导入并校验
  python3 import_cookies.py --browser chrome   # 指定浏览器
  python3 import_cookies.py --skip-check       # 频率限制时跳过联网校验
  python3 import_cookies.py --save-raw         # 额外导出 cookies_<用户名>.txt
  python3 import_cookies.py --save-session <路径>  # 自定义会话文件位置
  ```
- `test_login` 返回空时自动重试 3 次 × 30s
- 会话输出：`~/.config/instaloader/session-<用户名>`
- ⚠️ macOS 首次读取 Edge cookies 会弹 Keychain 授权框（"Microsoft Edge Safe Storage"）

### `fetch_all_followers.py` — 极端稳健的粉丝采集器

- 专为大粉丝量账号设计
- 保守速率控制（2s 延迟 + 429 重试）
- 每 10 页自动保存进度
- 支持 Ctrl+C 优雅退出
- 限流防护：`--skip-check`（跳过 `test_login` 校验）、
  `--max-consec-429 N`（连续被限流 N 次即保存退出，默认 5，避免无限等待）
- 输出：`{username}__all_followers.json`、`{username}__follower_usernames.txt`

### `analyze_followers.py` — 粉丝关注关系分析

- 分析指定用户的关注列表详细信息
- 使用浏览器 Cookie 登录（Edge/Chrome/Firefox）
- 通过 Web API 获取数据（规避 GraphQL 限制）
- 输出：`{username}__analysis.json`

### `analyze_kasc0206.py` — 批量用户详情采集（支持断点续传）

- **三种运行模式**：
  - 首次运行：直接执行 `python3 analyze_kasc0206.py`
  - 断点续传：`python3 analyze_kasc0206.py --resume`
  - 跳过登录验证：`python3 analyze_kasc0206.py --resume --skip-check`
  - 自动批量：`python3 analyze_kasc0206.py --auto --skip-check`
- 每次获取 25 个用户详情，频率受限时自动等待
- 待获取判定：以 `follower_count` 键是否存在为准（**真 0 粉丝也算已获取**）；
  单用户连续失败 3 次后写入 `_fetch_failed` 计数并跳过，避免 `--auto` 死循环
- 等待倒计时由 `--auto` 统一负责，`--resume` 不阻塞
- 输出：`kasc0206_analysis.json`

> ℹ️ 当前 `kasc0206_analysis.json` 中 552 个关注**已全部采集完毕**，`--resume` 无待办。

### `analyze_mutual.py` — 相互关注用户详情

- 获取指定相互关注用户的详细信息
- 表格形式输出用户名、粉丝数、关注数、帖子数等

### `ins_downloader.py` — 通用下载工具

- 支持浏览器 Cookie 登录或用户名密码
- 支持下载 Profile、Story、Highlight、Reels、Hashtag 等
- **增量更新三档模式**（理解区别很重要）：

  | 参数 | 行为 | 适用场景 |
  |---|---|---|
  | `--fast` | 遇第一个已存在的帖子就**停止** | 内容连续、无历史缺口 |
  | `--fill-gaps` | 逐帖比对本地日期戳，只下缺失的，**不提前停止** | **有历史缺口时唯一可靠的方式** |
  | 都不加 | 全量遍历（已存在的自动跳过） | 首次下载 |

- ⚠️ **`fast_update` 不会自愈**：它假设「帖子按时间倒序，遇已存在则其后必已下载」。
  只要列表中间有缺口（例如首次下载被限流中断），缺口**永远不会被补上** ——
  表现为核验显示「最新无缺失」，实际历史大量空白。
  实测 `--fill-gaps` 一次性补回 **9078 个文件**（`alicasmd` +4726、`xxcira` +1909、`____ylei` +971）。
- `--update-all`：扫描输出目录下所有用户目录逐个增量更新。默认只下帖子
  （跳过 Stories/Highlights/Tagged/Reels/IGTV —— 这些依赖的接口易被限流），
  且不强制下载头像（头像走 `i.instagram.com`，该端点当前返回 `status: fail`，
  每用户会白重试 3 次）
- **死账号自动跳过**：用户已删除/改名时（`ProfileNotExistsException`）自动记入
  `<输出目录>/_gone_accounts.txt`（每行 `用户名<TAB>日期[<TAB>原因]`），
  后续 `--update-all` 直接跳过、不再浪费请求。名单可手工编辑
- 批量下载：`--batch-file <列表文件>` / `--batch-resume`（断点保存在 `<输出目录>/.batch_state.json`，
  结构为 `all` + `index` + `completed`，失败用户不记入断点）
- 限流防护：`--skip-check`（跳过 `test_login` 校验）、
  `--no-wait-429`（遇 429 立即报错退出，不进入长时间休眠）
- 示例：

  ```bash
  # 单用户增量更新（限流时快速失败，不卡住）
  python3 ins_downloader.py --load-cookies edge --url <用户名> --fast --skip-check --no-wait-429

  # 全部用户：既更新最新，也补齐历史缺口（最常用）
  python3 ins_downloader.py --load-cookies edge --update-all --fill-gaps --no-wait-429

  # 批量下载（可中断后继续）
  python3 ins_downloader.py --load-cookies edge --batch-file users.txt --skip-check
  python3 ins_downloader.py --load-cookies edge --batch-resume --skip-check
  ```

### `verify_downloads.py` — 下载完整性核验

把**远端帖子列表**与**本地文件**逐个比对（按日期戳匹配文件名），找出缺失的帖子。

⚠️ **不要用文件 mtime 判断是否有更新**：instaloader 把媒体文件（`.jpg`/`.mp4`）的
mtime 设成**帖子发布时间**，只有 `.json.xz` 的 mtime 才是真实写入时间。
按 mtime 统计会严重低估，曾导致误判「已是最新」。

```bash
python3 verify_downloads.py                      # 核验 download_test 下所有用户
python3 verify_downloads.py --limit 30           # 每个用户只比对最近 30 个帖子
python3 verify_downloads.py llyrsnsx dodorisyu_  # 只核验指定用户
```

退出码：`0` = 全部完整；`1` = 存在缺失（可挂到定时任务）。

⚠️ **抽样核验有盲区**：`--limit 30` 只覆盖最近的帖子。若缺口集中在更早的历史，
核验会误报「无缺失」（曾因此把真实缺口 9000+ 文件误报为「仅 133 个」）。
要确认历史完整性，用「远端帖子数 vs 本地不同日期戳数」做全量对比，
或直接跑一遍 `--fill-gaps`（它遍历全部帖子）。

### 数据目录中的 `:tagged` 子目录

若曾用 `--tagged` 下载过被 @ 的内容，instaloader 会放在 `<用户目录>/:tagged/`。
统计文件数时注意区分，否则会与主目录数据混淆（当前 8 个用户共 1219 个 tagged 文件）。
`--update-all` 不下载 tagged，因此这些内容不随增量更新变化。

## 数据文件格式

### `{username}__all_followers.json`

```json
{
  "{username}": ["user1", "user2", ...]
}
```

### `{username}__follower_usernames.txt`

纯文本，每行一个用户名。

### `{username}__analysis.json`

```json
{
  "profile": {
    "username": "...",
    "userid": 123456,
    "followers_count": 1000,
    "followees_count": 100
  },
  "followees": [
    {
      "pk": "304322120",
      "username": "user1",
      "full_name": "全名",
      "is_private": false,
      "is_verified": false,
      "follower_count": 100,
      "following_count": 50,
      "media_count": 10
    }
  ]
}
```

### `{username}__fetch_state.json`

```json
{
  "end_cursor": "...",
  "has_next": true,
  "count": 100
}
```

### Instaloader 会话文件

- 路径：`~/.config/instaloader/session-<用户名>`（macOS/Linux，由 `get_default_session_filename()` 决定）
- 由 `import_cookies.py` 或 `Instaloader.save_session_to_file()` 生成
- 加载：`loader.load_session_from_file("<用户名>")`
- 权限 `600`，含 sessionid，**不要提交到 git**

## 版本控制与分支策略

- **默认分支**：`master`
- **origin**：`https://github.com/kasc0206/instaloader.git`（自己的 fork，可自由 push）
- **upstream**：`https://github.com/instaloader/instaloader.git`（原仓库，**只 fetch，不要 push**）
- **当前基线**：已 rebase 到上游 `v4.15.3`（commit `7efc78d`），落后 0，本地领先若干提交
- **本地版本号**：`4.15.3+local1`（PEP 440 local version，**不要**再冒充上游版本号如 `4.15.4`）
- **本地标签**：自己的里程碑标签一律用 `local-` 前缀（如 `local-4.15.2`），
  否则会与上游同名 tag 冲突，导致 `git fetch` 报 `would clobber existing tag`
- **上游标签**：`v4.15` / `v4.15a1` / `v4.15.1` / `v4.15.2` / `v4.15.3` 应与上游保持一致
- **备份**：升级前留有 `backup-pre-upgrade-20260917` 分支与 `backup-20260917` 标签
- **与上游同步流程**：
  1. 先确认本地没有脏标签（见上）
  2. `git fetch upstream --tags --prune`
  3. `git rebase upstream/master`，预期冲突集中在
     `instaloader/__init__.py`（版本号）、`instaloadercontext.py`、`structures.py`
  4. 冲突取舍原则：**上游已实现同名能力时采用上游**（上游已自带 `web_profile_info` 方案），
     仅保留上游没有的本地增强（如 `Post._obtain_metadata` 的 Web API 优先路径）
  5. 完成后 `git push origin master --tags`

> ⚠️ 保存 `.py` 文件前注意：用户级设置开启了 formatOnSave，Ruff 会把上游风格代码全量重排。
> 本项目已用 `.vscode/settings.json` 关闭 Python 的保存时自动格式化，不要删掉它。

### 上游已自带的能力（本地勿重复实现）

上游 v4.15.2+ 已自行修复了 GraphQL 限制问题，本地 fork 中重复的实现应优先删除：

- `Profile.from_username` / `Profile.from_id` / `Profile._obtain_metadata`（匿名）
  —— 上游改用 `api/v1/users/web_profile_info/` 与 `api/v1/users/{id}/info/`
- `Post._obtain_metadata` —— 上游改用 `doc_id 27128499623469141` + `Post._normalize_post_data`
- `InstaloaderContext._get_json` —— 上游已内置 CSRF 获取与注入、`x-ig-app-id` header
- **仍为本地独有**：`Post._obtain_metadata_via_web_api()`（REST `/api/v1/media/{id}/info/` 优先，
  GraphQL 回退）、`_convert_api_item_to_graphql()`（供 NodeIterator 的 Web API 路径使用）

## 常见工作流

### 🚦 请求频率规范（新增脚本必读）

**上游 instaloader `RateController` 的参数**（`instaloadercontext.py`）：

| 端点类型                                   | 上限   | 滑动窗口 | 等效间隔    |
| ------------------------------------------ | ------ | -------- | ----------- |
| `other`（www 的 REST，如 `friendships/*`） | 75 次  | 660 秒   | ≈ 8.8 秒/次 |
| `graphql` / `doc_id`                       | 200 次 | 660 秒   | ≈ 3.3 秒/次 |
| 所有 graphql 累计                          | 275 次 | 600 秒   | —           |
| `iphone`（i.instagram.com）                | 199 次 | 1800 秒  | ≈ 9 秒/次   |

**⚠️ 历史教训**：本项目的自定义脚本原先直接用 `requests.Session.get()`，
完全绕过了限速 —— `fetch_all_followers.py` 是 **2 秒/页**，比上游 `other` 类
允许的 8.8 秒**快 4.4 倍**，这是被限流的主要原因。

**现在统一使用 `rate_limiter.py`**：

```python
from rate_limiter import add_profile_args, get_limiter

limiter = get_limiter()      # 单例，默认 upstream 档位
limiter.acquire(url)         # 请求前调用：必要时等待并登记
resp = session.get(url, ...)
if resp.status_code == 429:
    limiter.penalize(url)    # 递增冷却（60s 起，上限 30 分钟）
else:
    limiter.reward()         # 成功后逐步消除惩罚
```

档位通过 `--rate-profile` 选择：`upstream`（默认，严格遵循上游）/
`conservative`（上游的 70%，已出现 429 时用）/ `off`（不主动限速，自担风险）。

**已接入**：`fetch_all_followers.py`、`analyze_kasc0206.py`、`analyze_followers.py`；
库侧 fork 新增的 Web API 方法（media info / feed user / usertags / igtv）
通过 `_wait_before_web_api_call()` 接入上游 `RateController`。

**新增脚本时**：凡绕过 `InstaloaderContext.get_json()` 直接发请求的，
都必须调用 `get_limiter().acquire(url)`。

### ⚠️ 遇到 429 限流怎么办（高频问题）

**关键结论：Instagram 的限流是「按端点」的，不是整个 IP 被封。**

实测（同一 IP、同一 cookies，2026-09-18）：

| 端点                                      | 用途                 | 状态                           |
| ----------------------------------------- | -------------------- | ------------------------------ |
| `api/v1/friendships/{id}/followers/`      | 粉丝列表             | ✅ 200 可用                    |
| `api/v1/friendships/{id}/following/`      | 关注列表             | ✅ 200 可用                    |
| `api/v1/users/edit/`                      | `test_login()`       | ✅ 200 可用                    |
| `web/search/topsearch/`                   | 用户名 → user_id     | ✅ 200 可用                    |
| `graphql/query?doc_id=27937681195819736`  | 用户资料（GraphQL）  | ✅ 200 可用                    |
| `api/v1/users/web_profile_info/`          | 用户资料             | ❌ 429 / 400 feedback_required |
| `api/v1/feed/user/{id}/`                  | 帖子列表（Feed API） | ❌ 302 / 400                   |
| `i.instagram.com/api/v1/users/{id}/info/` | App 资料             | ❌ fail（缺设备签名）          |

**代码已内置自动回退，一般不需要手动干预**：

1. **`Profile.from_username()`**：`web_profile_info` 返回 429/403/400 时，
   自动改用 `web/search/topsearch/` 解析 user_id，再走 GraphQL profile 查询
   补全元数据（见 `Profile._resolve_user_id_via_search()`）
2. **`get_posts_via_feed_api()`**：Feed API 失效时自动回退到标准
   `get_posts()`（GraphQL），见 `_fallback_to_graphql()`
   —— 修掉了此前"生成器静默结束 → 下载 0 个帖子却显示成功"的坑

因此限流期间增量更新与粉丝采集都能正常跑：

```bash
# 单用户增量更新（无需 --skip-check，test_login 走的是未被限流的端点）
python3 ins_downloader.py --load-cookies edge --url <用户名> --fast --no-wait-429

# 粉丝采集（用 --user-id 或本地 *_analysis.json 解析 user_id，完全不碰 web_profile_info）
python3 fetch_all_followers.py --max-pages 200
```

**为什么浏览器"能正常访问"但脚本被限流**：浏览网页走 HTML 与另外的 API，
和被限流的 `web_profile_info` 不在同一个限流桶里。
（资料页 HTML 里嵌的 `PolarisViewer` 数据块是**当前登录者本人**的信息，不是被查看用户的，
所以不能拿来替代。）

**判断方法**（不依赖 instaloader，几秒出结果）：

```bash
python3 -c "import requests; print(requests.get('https://www.instagram.com/api/v1/users/web_profile_info/?username=natgeo', timeout=5).status_code)"
```

**为什么以前会"卡住"**：instaloader 的 `RateController.handle_429()` 会
`sleep(waittime)` 等待（可能数十分钟），期间只打印一行提示。若再用
`| tail` 之类的管道过滤输出，缓冲会让等待期完全不可见。
`--no-wait-429`（`ins_downloader.py`）与 `--max-consec-429 N`（`fetch_all_followers.py`）
可让它立即失败。

**解除限流的手段**：等待（通常数十分钟到数小时）或更换出口 IP（切换网络最有效）。
被限流期间不要反复重试，会延长封锁时间。

### 0. 刷新登录状态（前置步骤）

所有需要登录的脚本都依赖浏览器 cookies，cookie 失效时先执行：

```bash
# 在 Edge 中重新登录 Instagram 后，导入最新 cookies
python3 import_cookies.py

# 触发频率限制时
python3 import_cookies.py --skip-check
```

### 1. 增量数据采集

运行 VS Code Task 或手动执行脚本：

```bash
# 初次采集粉丝列表
python3 fetch_all_followers.py chrissylii_

# 增量获取关注者详情（断点续传）
python3 analyze_kasc0206.py --resume --skip-check

# 自动循环采集
python3 analyze_kasc0206.py --auto --skip-check
```

### 1.5 下载内容增量更新

```bash
# 全部用户：更新最新 + 补齐历史缺口（推荐，一次搞定）
python3 ins_downloader.py --load-cookies edge --update-all --fill-gaps --no-wait-429

# 只想快速看有没有新帖（有历史缺口时慎用，见上文 ins_downloader.py 说明）
python3 ins_downloader.py --load-cookies edge --update-all --fast --no-wait-429

# 更新完核验完整性
python3 verify_downloads.py --limit 30
```

⚠️ 长时间运行请**重定向到日志文件**并后台执行，不要用 `| tail` ——
管道缓冲会让进程看起来像卡死，且 `head` 会因 SIGPIPE 直接杀掉 Python 进程。

### 2. 测试修改

```bash
# ⚠️ 本机未安装 pytest，使用标准库 unittest（必须在项目根目录执行）
python3 -u -m unittest test.instaloader_unittests -v

# 只跑单个用例
python3 -u -m unittest test.instaloader_unittests.TestInstaloaderAnonymously.test_get_id_by_username
```

- ⚠️ `test/instaloader_unittests.py` 是**联网集成测试**（真实下载 selenagomez/natgeo 等），
  全套耗时数分钟以上
- ⚠️ 不要写成 `python3 test/instaloader_unittests.py`，会 `ModuleNotFoundError`
- ⚠️ 不要用 `| tail` 过滤输出，管道缓冲会导致看不到实时进度

### 3. 代码检查

```bash
ruff check .
mypy instaloader/
```

## API 异常处理规则

- Instagram 经常封锁 API 请求，所有网络请求必须包含**重试机制**
- 403 错误：切换 API 端点（GraphQL → Feed API → Web API）
- 429 错误（频率限制）：指数退避等待
- `InstaloaderContext` 中的 `request()` 方法已包含重试逻辑
- 如果新增 API 调用，请参考 `instaloadercontext.py` 中的重试模式

## 编码约定

- Python 3.8+，类型注解
- 使用 `ruff` 进行代码检查
- 公开 API 需要类型标注
- 网络请求超时默认 15 秒
- Cookie 文件名：`cookies_{username}.txt`
- 会话文件名：`session-{username}`
