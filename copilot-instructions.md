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
├── import_cookies.py             # 浏览器 Cookie 导入 / 会话生成
├── fetch_all_followers.py        # 粉丝采集器
├── analyze_followers.py          # 粉丝关注关系分析
├── analyze_kasc0206.py           # 批量用户详情采集
├── analyze_mutual.py             # 相互关注用户详情
├── ins_downloader.py             # 通用下载工具
├── download_test/                # 已下载的 Instagram 用户资料
│   ├── chrissylii_/
│   ├── pikapikammmmm/
│   └── ...（共 ~16 个用户）
├── docs/                         # Sphinx 文档
├── deploy/                       # 部署配置
├── test/                         # 单元测试（联网集成测试，见下）
└── .vscode/tasks.json            # 常用任务
```

## 自定义脚本

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
- 支持快速增量更新（`--fast-update`）
- 批量下载：`--batch-file <列表文件>` / `--batch-resume`（断点保存在 `<输出目录>/.batch_state.json`，
  结构为 `all` + `index` + `completed`，失败用户不记入断点）
- 限流防护：`--skip-check`（跳过 `test_login` 校验）、
  `--no-wait-429`（遇 429 立即报错退出，不进入长时间休眠）
- 示例：

  ```bash
  # 单用户增量更新（限流时快速失败，不卡住）
  python3 ins_downloader.py --load-cookies edge --url <用户名> --fast --skip-check --no-wait-429

  # 批量下载（可中断后继续）
  python3 ins_downloader.py --load-cookies edge --batch-file users.txt --skip-check
  python3 ins_downloader.py --load-cookies edge --batch-resume --skip-check
  ```

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

### ⚠️ 遇到 429 限流怎么办（高频问题）

**关键结论：Instagram 的限流是「按端点」的，不是整个 IP 被封。**

实测（同一 IP、同一 cookies，2026-09-18）：

| 端点                                             | 用途                | 状态                        |
| ------------------------------------------------ | ------------------- | --------------------------- |
| `api/v1/friendships/{id}/followers/`             | 粉丝列表            | ✅ 200 可用                 |
| `api/v1/friendships/{id}/following/`             | 关注列表            | ✅ 200 可用                 |
| `api/v1/users/edit/`                             | `test_login()`      | ✅ 200 可用                 |
| `web/search/topsearch/`                          | 用户名 → user_id    | ✅ 200 可用                 |
| `graphql/query?doc_id=27937681195819736`         | 用户资料（GraphQL） | ✅ 200 可用                 |
| `api/v1/users/web_profile_info/`                 | 用户资料            | ❌ 429 / 400 feedback_required |
| `api/v1/feed/user/{id}/`                         | 帖子列表（Feed API）| ❌ 302 / 400                |
| `i.instagram.com/api/v1/users/{id}/info/`        | App 资料            | ❌ fail（缺设备签名）       |

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
