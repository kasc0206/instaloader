# 本地改动清单（fork 相对上游的净增量）

> **用途**：与上游同步（`git rebase upstream/master`）时照着本清单逐条处理，
> 不必重新推理每一处改动的意图。
>
> 更新于 2026-09-18（本地领先上游 30 个提交，落后 0；上游版本 v4.15.3）。

## 一、风险总览：隐患比「564 行」给人的印象小得多

核心库 4 个文件共 **686 行新增 / 62 行删除**：

| 文件                                |    新增 |   删除 | 冲突风险             |
| ----------------------------------- | ------: | -----: | -------------------- |
| `instaloader/structures.py`         |     550 |     14 | 中                   |
| `instaloader/instaloader.py`        |     132 |     46 | 中高                 |
| `instaloader/__init__.py`           |       2 |      2 | 低（但**必然**冲突） |
| `instaloader/instaloadercontext.py` |       2 |      0 | 极低                 |
| **合计**                            | **686** | **62** | —                    |

**关键结论：686 行（92%）是纯新增代码块，`git` 三方合并能自动处理；
真正会与上游「争抢同一行」的只有 62 行，集中在下面 10 处。**

而且这 10 处中有 6 处是**同一个模式**（把上游原实现包进 `except` 分支做回退），
上游原始代码在本地**完整保留**，所以冲突解法是机械的 —— 相当于**填空**，不是重写。

## 二、高危改动清单（rebase 时重点看这里）

| #   | 位置                            | 改动内容                                              | 冲突时的解法                                            |
| --- | ------------------------------- | ----------------------------------------------------- | ------------------------------------------------------- |
| 1   | `__init__.py` 版本号            | `'4.15.3'` → `'4.15.3+local1'`                        | 用**上游新版本号** + 保留 `+local1` 后缀                |
| 2   | `__init__.py` 导出              | `from .exceptions import *` 补 `# noqa: F401, F403`   | 保留本地 `# noqa` 注释                                  |
| 3   | `InstaloaderContext._get_json`  | 新增 `403 → QueryReturnedBadRequestException`（2 行） | 直接保留本地                                            |
| 4   | `Instaloader.download_tagged`   | 上游实现整体包进 `try/except`，优先走 Web API         | **保留外层 try 包装，把 `except` 分支内容换成上游新版** |
| 5   | `Instaloader.download_reels`    | 同上                                                  | 同上                                                    |
| 6   | `Instaloader.download_igtv`     | 同上                                                  | 同上                                                    |
| 7   | `Instaloader.download_profile`  | 新增 `_feed_posts_wrapper` 包装 feed API              | 同上                                                    |
| 8   | `Instaloader.interactive_login` | 登录流程微调                                          | 上游若已改则**用上游**                                  |
| 9   | `Post._obtain_metadata`         | 上游 GraphQL 查询包进 `except`，优先 Web API          | 同 #4                                                   |
| 10  | `load_structure`                | 1 行调整                                              | 上游若已改则**用上游**                                  |

> 通用原则（沿用既有约定）：
> 上游已实现同名能力 → **用上游**，删掉本地重复实现；
> 本地独有能力（`_obtain_metadata_via_web_api`、`_convert_api_item_to_graphql`、
> `get_*_via_api`）→ **保留本地**，把上游新版塞进回退分支。

## 三、纯新增、几乎不会冲突的部分

以下都是**独立新增的函数/代码块**，除非上游正好在同一位置插入代码，
否则 rebase 不会报冲突：

- `structures.py`
  - 模块级 `_convert_api_item_to_graphql()` 等（+107）
  - `Post._obtain_metadata_via_web_api()`
  - `Profile.get_posts_via_feed_api()` / `_fallback_to_graphql()`（+341）
  - `Profile._resolve_user_id_via_search()` 等（+35）
- `instaloader.py`
  - `get_tagged_posts_via_api()` / `get_reels_via_api()` / `get_igtv_posts_via_api()`
  - `_feed_posts_wrapper()`
- **全部自定义脚本**（上游完全没有这些文件，**永不会冲突**）

  `rate_limiter.py`、`import_cookies.py`、`fetch_all_followers.py`、`analyze_followers.py`、
  `analyze_kasc0206.py`、`analyze_mutual.py`、`ins_downloader.py`、`verify_downloads.py`、
  `copilot-instructions.md`、`LOCAL_CHANGES.md`、`.vscode/*`

## 四、上游同步流程

```bash
# 1. 先打备份标签（保险，出问题可一键回退）
git tag pre-sync-$(date +%Y%m%d)

# 2. 拉取上游
git fetch upstream --tags --prune

# 3. 先看上游改了什么，再动手
git log --oneline HEAD..upstream/master
git diff --stat upstream/master -- instaloader/

# 4. rebase（rerere 已启用，会自动套用记住的冲突解法）
git rebase upstream/master

# 5. 验证
python3 -m py_compile instaloader/structures.py instaloader/instaloader.py
python3 verify_downloads.py <任一用户> --limit 10     # 冒烟测试

# 6. 推送（rebase 后需要 force，用 --force-with-lease 更安全）
git push --force-with-lease origin master
git push origin --tags
```

**重要：不要等上游发版才同步。** 每月（或每两周）跑一次
`fetch + rebase`，上游每次只前进几个提交，冲突概率和规模都极小；
攒一年再同步才会面对堆积如山的大冲突。

## 五、防护措施现状

| 措施                                             | 状态                                                         |
| ------------------------------------------------ | ------------------------------------------------------------ |
| `git rerere`（冲突解法自动记忆/复用）            | ✅ 已启用（`rerere.enabled=true`、`rerere.autoupdate=true`） |
| `.vscode/settings.json` 关闭 Python 保存时格式化 | ✅ 已配置（防 Ruff 重排上游代码）                            |
| 备份分支                                         | ✅ `backup-pre-upgrade-20260917`                             |
| 备份标签                                         | ✅ `local-4.15.2/3/4`、`backup-20260917`                     |
| `upstream` 推送保护                              | ✅ push URL 设为 `DISABLE_PUSH_TO_UPSTREAM`                  |
| `# [LOCAL]` 代码标记                             | ⏳ 约定见下，尚未在代码中标注                                |

## 六、`# [LOCAL]` 标记约定（可选，建议采用）

给第二节表中的 10 处本地改动加上统一注释标记：

```bash
grep -rn "\[LOCAL\]" instaloader/
```

rebase 报冲突时，一眼就能分清「这段是我的」和「这段是上游的」，
不用逐行比对语义。
