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
- 输入：用户名列表文件
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
- 输出：`kasc0206_analysis.json`

### `analyze_mutual.py` — 相互关注用户详情

- 获取指定相互关注用户的详细信息
- 表格形式输出用户名、粉丝数、关注数、帖子数等

### `ins_downloader.py` — 通用下载工具

- 支持浏览器 Cookie 登录或用户名密码
- 支持下载 Profile、Story、Highlight、Reels、Hashtag 等
- 支持快速增量更新（`--fast-update`）

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
