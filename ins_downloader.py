#!/usr/bin/env python3
"""
Instagram 下载工具 - Fork of Instaloader
=========================================
基于 Instaloader 4.15.1，修复了 Instagram API 兼容性问题。
通过 Web API 替代被限制的 graphql/query 端点。

用法:
  # 从浏览器导入 cookies 登录（推荐）
  python ins_downloader.py --load-cookies edge --url https://www.instagram.com/username/ --all --avatar

  # 使用用户名密码登录，下载特定内容
  python ins_downloader.py --login username --url natgeo --stories --highlights --reels --tagged

  # 仅下载公开内容（无需登录，但部分功能受限）
  python ins_downloader.py --url public_profile

  # 更新所有已下载的用户（快速增量更新）
  python ins_downloader.py --load-cookies edge --update-all
"""

import argparse
import getpass
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import List

# 确保可以找到本地修改后的 instaloader 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import instaloader
from instaloader import Post, Profile, ProfileNotExistsException

# 支持的浏览器列表
SUPPORTED_BROWSERS = ["brave", "chrome", "chromium", "edge", "firefox",
                       "librewolf", "opera", "opera_gx", "safari", "vivaldi"]

# 记录已确认不存在的账号（被删除/改名），--update-all 时自动跳过
GONE_ACCOUNTS_NAME = "_gone_accounts.txt"


def load_gone_accounts(output_dir: Path) -> set:
    """读取「已不存在账号」名单。每行格式：用户名<TAB>日期[<TAB>原因]"""
    path = output_dir / GONE_ACCOUNTS_NAME
    if not path.is_file():
        return set()
    names = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(line.split("\t")[0].strip())
    except OSError as e:
        print(f"⚠️ 读取 {GONE_ACCOUNTS_NAME} 失败: {e}")
    return names


def mark_gone_account(output_dir: Path, username: str, reason: str = "",
                      already: set = None) -> None:
    """把确认不存在的账号记入名单，避免每次 --update-all 都白跑一趟。"""
    if already is not None and username in already:
        return
    path = output_dir / GONE_ACCOUNTS_NAME
    line = f"{username}\t{time.strftime('%Y-%m-%d')}"
    if reason:
        line += f"\t{reason}"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        if already is not None:
            already.add(username)
        print(f"  📝 已记入 {GONE_ACCOUNTS_NAME}，后续自动跳过: {username}")
    except OSError as e:
        print(f"  ⚠️ 无法写入 {GONE_ACCOUNTS_NAME}: {e}")


class FailFastRateController(instaloader.RateController):
    """遇 HTTP 429 立即失败，而不是进入长时间休眠。

    instaloader 默认的 :class:`RateController` 在收到 429 时会调用
    ``sleep(waittime)`` 等待（可能长达数十分钟），进程看起来就像卡死了。
    使用本控制器（配合 ``--no-wait-429``）可让它立刻报错退出。
    """

    def handle_429(self, query_type: str) -> None:
        raise instaloader.TooManyRequestsException(
            "Instagram 返回 429（频率限制），已按 --no-wait-429 立即中止。"
            "请稍后重试或更换出口 IP。"
        )


def parse_instagram_url(url_or_username: str) -> str:
    """从 Instagram 链接或用户名中提取用户名"""
    url_or_username = url_or_username.strip().rstrip("/")
    patterns = [
        r"(?:https?://)?(?:www\.)?instagram\.com/([a-zA-Z0-9_.]+)",
        r"^([a-zA-Z0-9_.]+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, url_or_username)
        if match:
            username = match.group(1)
            if username.lower() in ["explore", "p", "reel", "tv", "stories",
                                    "accounts", "direct", "about", "legal"]:
                continue
            return username
    raise ValueError(f"无法从 '{url_or_username}' 中提取有效的 Instagram 用户名")


def read_urls_from_file(file_path: str) -> List[str]:
    """从文件读取链接列表"""
    urls = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def load_cookies_from_browser(loader: instaloader.Instaloader, browser: str,
                              skip_login_check: bool = False):
    """从浏览器导入 Instagram cookies

    :param skip_login_check: 跳过 ``test_login()`` 联网校验。
        用于 Instagram 限流（429）导致校验必定失败、但 cookies 本身仍有效的场景。
    """
    try:
        import browser_cookie3
    except ImportError:
        print("❌ 请先安装 browser_cookie3: pip install browser_cookie3")
        sys.exit(1)

    browser_map = {
        "brave": browser_cookie3.brave,
        "chrome": browser_cookie3.chrome,
        "chromium": browser_cookie3.chromium,
        "edge": browser_cookie3.edge,
        "firefox": browser_cookie3.firefox,
        "librewolf": browser_cookie3.librewolf,
        "opera": browser_cookie3.opera,
        "opera_gx": browser_cookie3.opera_gx,
        "safari": browser_cookie3.safari,
        "vivaldi": browser_cookie3.vivaldi,
    }

    if browser.lower() not in browser_map:
        print(f"❌ 不支持的浏览器: {browser}")
        print(f"   支持的浏览器: {', '.join(SUPPORTED_BROWSERS)}")
        sys.exit(1)

    print(f"🔑 正在从 {browser} 导入 Instagram cookies...")
    try:
        cookies = {}
        for cookie in browser_map[browser.lower()](domain_name="instagram.com"):
            if "instagram.com" in cookie.domain:
                cookies[cookie.name] = cookie.value

        if not cookies:
            print(f"❌ 在 {browser} 中未找到 Instagram cookies。请确保已在 {browser} 中登录 Instagram。")
            sys.exit(1)

        loader.context.update_cookies(cookies)

        if skip_login_check:
            # 限流时 test_login() 必定失败，直接信任 cookies
            username = cookies.get("ds_user") or "unknown"
            loader.context.username = username
            print(f"⚠️  已跳过登录验证（--skip-check），用户名标记为 {username}")
            if username == "unknown":
                print("   （cookie 中无 ds_user；若后续请求失败，请重新在浏览器中登录 Instagram）")
        else:
            username = loader.test_login()
            if not username:
                print(f"❌ cookies 导入成功但未检测到登录状态，请重新在 {browser} 中登录 Instagram。")
                print("   若正被限流（429），可加 --skip-check 跳过该校验。")
                sys.exit(1)

            loader.context.username = username
            print(f"✅ 已通过 {browser} 登录为 {username}")

        # 保存 session 文件供后续使用（用户名未知时不保存，避免生成 session-unknown）
        if username == "unknown":
            print("ℹ️  用户名未知，跳过保存会话文件")
        else:
            try:
                loader.save_session_to_file()
                print("💾 会话已保存到本地文件")
            except Exception:
                pass

        return username

    except Exception as e:
        print(f"❌ 从 {browser} 导入 cookies 失败: {e}")
        sys.exit(1)


def download_profile_content(loader: instaloader.Instaloader,
                              username: str,
                              download_stories: bool = False,
                              download_highlights: bool = False,
                              download_avatar: bool = False,
                              download_tagged: bool = False,
                              download_reels: bool = False,
                              download_igtv: bool = False,
                              fast_update: bool = False,
                              fill_gaps: bool = False,
                              gone_dir: Path = None) -> bool:
    """下载指定用户的所有内容

    :param fill_gaps: 补齐模式。不依赖 ``fast_update`` 的「遇到已存在就停」
        假设（该假设在帖子列表中间存在缺失时会失效，且无法自愈），
        改为逐个帖子比对本地是否已有该日期文件，只下载缺失的。
    :param gone_dir: 若指定，用户不存在时会把用户名记入该目录下的
        ``_gone_accounts.txt``，之后 ``--update-all`` 将自动跳过。
    :return: 是否成功（用户解析与整体下载未遇到致命异常）
    """
    try:
        profile = Profile.from_username(loader.context, username)

        print(f"\n{'='*60}")
        print(f"📥 开始下载: {profile.username}")
        print(f"   全名: {profile.full_name}")
        print(f"   帖子数: {profile.mediacount}")
        print(f"   粉丝: {profile.followers}")
        print(f"   关注: {profile.followees}")
        print(f"   用户ID: {profile.userid}")
        if profile.is_private:
            print("   🔒 私密账号")
        print("=" * 60)

        # 下载头像
        if download_avatar:
            print("\n📸 下载头像...")
            try:
                loader.download_profilepic(profile)
                print("  ✅ 头像已下载")
            except Exception as e:
                print(f"  ⚠️ 头像下载失败: {e}")

        # 下载所有帖子
        print("\n📥 下载帖子...")
        post_filter = None
        if fill_gaps:
            # 只在补齐模式下启用：把「本地已有该日期文件」的帖子过滤掉。
            # post_filter 返回 False 只会跳过单个帖子，不会像 fast_update 那样 break，
            # 因此列表中间的历史缺失也能被补齐。
            target_dir = Path(loader.dirname_pattern.format(target=profile.username))
            local = set(os.listdir(target_dir)) if target_dir.is_dir() else set()

            def _only_missing(post: Post) -> bool:
                stamp = post.date_utc.strftime("%Y-%m-%d_%H-%M-%S_UTC")
                return not any(f.startswith(stamp) for f in local)

            post_filter = _only_missing
            fast_update = False
            print(f"  🔍 补齐模式：本地已有 {len(local)} 个文件，只下载缺失的帖子")

        try:
            loader.download_profile(profile, profile_pic=False,
                                    fast_update=fast_update,
                                    post_filter=post_filter)
            print("  ✅ 帖子已下载")
        except Exception as e:
            print(f"  ⚠️ 帖子下载失败: {e}")

        # 下载 Stories
        if download_stories:
            print("\n📖 下载 Stories...")
            try:
                loader.download_stories(userids=[profile.userid],
                                        filename_target=profile.username)
                print("  ✅ Stories 已下载")
            except Exception as e:
                print(f"  ⚠️ Stories 下载失败: {e}")

        # 下载 Highlights
        if download_highlights:
            print("\n⭐ 下载 Highlights（精选）...")
            try:
                loader.download_highlights(user=profile,
                                           filename_target=profile.username)
                print("  ✅ Highlights 已下载")
            except Exception as e:
                print(f"  ⚠️ Highlights 下载失败: {e}")

        # 下载 Tagged（标记用户的帖子）
        if download_tagged:
            print("\n🏷️ 下载标记的帖子...")
            try:
                loader.download_tagged(profile, fast_update=fast_update)
                print("  ✅ 标记的帖子已下载")
            except Exception as e:
                print(f"  ⚠️ 标记帖子下载失败: {e}")

        # 下载 Reels（短视频）
        if download_reels:
            print("\n🎬 下载 Reels 短视频...")
            try:
                loader.download_reels(profile, fast_update=fast_update)
                print("  ✅ Reels 已下载")
            except Exception as e:
                print(f"  ⚠️ Reels 下载失败: {e}")

        # 下载 IGTV（长视频）
        if download_igtv:
            print("\n📺 下载 IGTV 视频...")
            try:
                loader.download_igtv(profile, fast_update=fast_update)
                print("  ✅ IGTV 已下载")
            except Exception as e:
                print(f"  ⚠️ IGTV 下载失败: {e}")

        print(f"\n✅ {profile.username} 下载完成！")
        return True

    except ProfileNotExistsException:
        print(f"❌ 用户 '{username}' 不存在（账号已删除或改名）")
        if gone_dir is not None:
            mark_gone_account(gone_dir, username, "ProfileNotExists")
        return False
    except instaloader.PrivateProfileNotFollowedException:
        print(f"❌ 用户 '{username}' 是私密账号，你的账号未关注该用户")
        return False
    except instaloader.LoginRequiredException:
        print(f"❌ 需要登录才能访问 '{username}' 的内容")
        return False
    except instaloader.ConnectionException as e:
        error_msg = str(e)
        if "403" in error_msg:
            print(f"⚠️ 用户 '{username}' API 限制 (403 Forbidden)")
            print("   Instagram 临时限制了对该用户的访问，可稍后重试")
            print(f"   💡 单独重试: python3 ins_downloader.py --load-cookies edge --url {username} --fast")
        elif "429" in error_msg:
            print(f"⏳ 用户 '{username}' 触发频率限制 (429)")
            print("   请等待一段时间后重试，或更换出口 IP")
        else:
            print(f"❌ 连接错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 下载 '{username}' 时发生未知错误: {e}")
        return False


def save_batch_state(state_file: Path, all_users: List[str], done_users: List[str]) -> None:
    """写入批量下载断点状态。

    保存完整列表 ``all`` 与已完成数 ``index``，恢复时按索引切片，
    避免旧格式（只存 pending）恢复时二次切片导致跳过用户。
    """
    state = {
        'all': all_users,
        'index': len(done_users),
        'completed': done_users,
        'pending': all_users[len(done_users):],
    }
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(
        description="Instagram 下载工具 - 下载用户的所有图片、视频等资料",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s --login my_account --url https://www.instagram.com/natgeo/
  %(prog)s --login my_account --url natgeo selenagomez --stories --highlights --reels
  %(prog)s --login my_account --file urls.txt --all --avatar  (下载所有内容)
  %(prog)s --url public_profile  (无需登录，仅下载公开内容)
  %(prog)s --load-cookies edge --update-all  (更新所有已下载用户)
        """,
    )

    target_group = parser.add_argument_group("目标设置")
    target_group.add_argument("--url", nargs="*", dest="urls", default=None,
                              help="Instagram 用户链接或用户名")
    target_group.add_argument("--file", dest="url_file", default=None,
                              help="包含 Instagram 链接的文件路径")
    target_group.add_argument("--batch-file", dest="batch_file", default=None,
                             help="批量下载用户列表文件（每行一个用户名），支持断点续传")
    target_group.add_argument("--batch-resume", dest="batch_resume",
                             action="store_true",
                             help="恢复上次中断的批量下载任务")

    login_group = parser.add_argument_group("登录设置（下载私密内容必需）")
    login_group.add_argument("--login", dest="login_user", default=None,
                             help="Instagram 登录用户名")
    login_group.add_argument("--password", dest="password", default=None,
                             help="Instagram 登录密码（不提供则交互式输入）")
    login_group.add_argument("--load-cookies", dest="browser", default=None,
                             choices=SUPPORTED_BROWSERS,
                             help="从指定浏览器导入登录状态（推荐：edge）")
    login_group.add_argument("--skip-check", action="store_true",
                             help="跳过 test_login() 登录校验（限流 429 时使用，直接信任 cookies）")

    ratelimit_group = parser.add_argument_group("限流处理")
    ratelimit_group.add_argument("--no-wait-429", action="store_true",
                                 help="遇 429 立即报错退出，不进入长时间休眠（默认会按 RateController 等待）")

    download_group = parser.add_argument_group("下载选项")
    download_group.add_argument("--stories", action="store_true",
                                help="下载 Stories（快拍，24小时有效）")
    download_group.add_argument("--highlights", action="store_true",
                                help="下载 Highlights（精选故事）")
    download_group.add_argument("--tagged", action="store_true",
                                help="下载标记用户的帖子")
    download_group.add_argument("--reels", action="store_true",
                                help="下载 Reels 短视频")
    download_group.add_argument("--igtv", action="store_true",
                                help="下载 IGTV 长视频")
    download_group.add_argument("--avatar", action="store_true",
                                help="下载用户头像")
    download_group.add_argument("--all", action="store_true", dest="download_all",
                                help="下载所有内容（头像+帖子+Stories+Highlights+Tagged+Reels+IGTV）")
    download_group.add_argument("--fast", action="store_true", dest="fast_update",
                                help="快速模式，只下载新内容（注意：若历史上有遗漏，"
                                     "因帖子列表中间的「已存在」会提前停止，无法自愈；"
                                     "请用 --fill-gaps 修复）")
    download_group.add_argument("--fill-gaps", action="store_true",
                                help="补齐模式：逐个帖子比对本地文件，只下载缺失的（可修复历史遗漏）")
    download_group.add_argument("--output", "-o", default="download_test",
                                help="输出目录（默认 download_test 目录）")
    download_group.add_argument("--update-all", action="store_true",
                                help="更新所有已下载的用户（扫描输出目录，自动快速度更新）")
    download_group.add_argument("--quiet", "-q", action="store_true",
                                help="静默模式")

    args = parser.parse_args()

    output_dir = Path(args.output).resolve()

    # 收集目标用户名
    usernames = []

    # --update-all 模式：扫描输出目录中已有的用户
    if args.update_all:
        if output_dir.is_dir():
            gone = load_gone_accounts(output_dir)
            for entry in sorted(output_dir.iterdir()):
                if not entry.is_dir() or entry.name.startswith('.'):
                    continue
                if entry.name in gone:
                    continue
                usernames.append(entry.name)
            if gone:
                print(f"🚫 按 {GONE_ACCOUNTS_NAME} 跳过 {len(gone)} 个已不存在账号: "
                      f"{', '.join(sorted(gone))}")
            if usernames:
                print(f"🔄 更新模式：扫描到 {len(usernames)} 个已下载的用户")
            else:
                print(f"❌ 输出目录 '{output_dir}' 中未找到需更新的用户")
                sys.exit(1)
        else:
            print(f"❌ 输出目录 '{output_dir}' 不存在")
            sys.exit(1)
        # 更新模式默认使用快速模式
        args.fast_update = True
        # 更新模式只下载帖子（跳过 Stories/Highlights/Tagged/Reels/IGTV
        # 因为这些内容依赖的 graphql/query 接口容易被 Instagram 限制）
        args.download_all = False
        # 不强制下载头像：头像走 i.instagram.com 端点，该端点目前已不可用
        # （返回 status: fail），每个用户会白白重试 3 次、明显拖慢批量更新。
        # 确有需要时显式加 --avatar。
        if args.avatar:
            print("ℹ️  注意：头像依赖 i.instagram.com 端点，该端点当前不可用，可能失败")
    else:
        if args.urls:
            for url in args.urls:
                try:
                    usernames.append(parse_instagram_url(url))
                except ValueError as e:
                    print(f"⚠️ 跳过: {e}")
        if args.url_file:
            try:
                for url in read_urls_from_file(args.url_file):
                    try:
                        usernames.append(parse_instagram_url(url))
                    except ValueError as e:
                        print(f"⚠️ 跳过: {e}")
            except FileNotFoundError:
                print(f"❌ 文件不存在: {args.url_file}")
                sys.exit(1)

    # --batch-file 模式：批量下载，支持断点续传
    batch_all = None    # 完整待办列表（用于索引计算）
    batch_done = []     # 已完成的用户
    state_file = output_dir / ".batch_state.json"
    if args.batch_file or args.batch_resume:
        usernames = []  # 清空，batch 模式独立处理
        if args.batch_resume:
            # 恢复模式：从 state 文件中读取
            if not state_file.exists():
                print(f"❌ 未找到断点状态文件 {state_file}，无法恢复")
                sys.exit(1)
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
            except Exception as e:
                print(f"❌ 读取状态文件失败: {e}")
                sys.exit(1)

            batch_done = list(state.get('completed', []))
            if 'all' in state:
                # 新格式：完整列表 + 已完成数，按索引切片
                done = state.get('index', len(batch_done))
                batch_all = list(state['all'])
                usernames = batch_all[done:]
                print(f"🔄 恢复上次任务：已完成 {done} 个，待下载 {len(usernames)} 个")
            else:
                # 旧格式：pending 已是剩余列表，绝不能再按 index 二次切片
                usernames = list(state.get('pending', []))
                batch_all = batch_done + usernames
                print(f"🔄 恢复上次任务（旧格式状态文件）："
                      f"已完成 {len(batch_done)} 个，待下载 {len(usernames)} 个")
            if batch_done:
                print(f"   最近完成: {', '.join(batch_done[-5:])}")
            if usernames:
                print(f"   下一个: @{usernames[0]}")
        else:
            # 首次批量模式：读取用户列表文件
            try:
                with open(args.batch_file, 'r', encoding='utf-8') as f:
                    batch_users = [line.strip() for line in f
                                   if line.strip() and not line.startswith('#')]
            except FileNotFoundError:
                print(f"❌ 文件不存在: {args.batch_file}")
                sys.exit(1)

            # 跳过已下载的用户
            if output_dir.is_dir():
                existing = {d.name for d in output_dir.iterdir()
                           if d.is_dir() and not d.name.startswith('.')}
                batch_users = [u for u in batch_users if u not in existing]
                if existing:
                    print(f"⏭️  跳过 {len(existing)} 个已下载用户")

            print(f"📋 批量下载任务：共 {len(batch_users)} 个用户")
            usernames = batch_users
            batch_all = list(batch_users)

            # 保存初始状态
            save_batch_state(state_file, batch_all, batch_done)

        # 批量模式默认使用快速模式+头像
        if not args.stories and not args.highlights and not args.tagged \
                and not args.reels and not args.igtv and not args.download_all:
            args.fast_update = True
            args.avatar = True
    elif not usernames:
        print("❌ 未指定目标用户。使用 --url、--file、--batch-file 或 --update-all。")
        parser.print_help()
        sys.exit(1)

    # 初始化 Instaloader
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    loader = instaloader.Instaloader(
        dirname_pattern=str(output_dir / "{target}"),
        filename_pattern="{date_utc}_UTC",
        download_pictures=True,
        download_videos=True,
        download_video_thumbnails=True,
        save_metadata=True,
        compress_json=True,
        quiet=args.quiet,
        # --no-wait-429：用自定义控制器替代默认的“睡眠等待”行为
        rate_controller=FailFastRateController if args.no_wait_429 else None,
    )

    # 登录方式
    if args.browser:
        # 方式1: 从浏览器导入 cookies（推荐）
        load_cookies_from_browser(loader, args.browser, args.skip_check)

    elif args.login_user:
        # 方式2: 用户名密码登录
        login_user = args.login_user
        password = args.password
        try:
            loader.load_session_from_file(login_user)
            print(f"✅ 已加载 {login_user} 的会话")
        except FileNotFoundError:
            print(f"🔑 正在登录 {login_user}...")
            if password is None:
                password = getpass.getpass(f"请输入 {login_user} 的密码: ")
            try:
                loader.login(login_user, password)
                loader.save_session_to_file()
                print("✅ 登录成功！会话已保存")
            except instaloader.TwoFactorAuthRequiredException:
                print("🔐 需要两步验证...")
                code = input("请输入 2FA 验证码: ")
                loader.two_factor_login(code)
                loader.save_session_to_file()
                print("✅ 验证成功！")
            except instaloader.BadCredentialsException:
                print("❌ 用户名或密码错误")
                sys.exit(1)
            except instaloader.ConnectionException as e:
                print(f"❌ 登录失败: {e}")
                sys.exit(1)

    # 提示登录状态
    if loader.context.is_logged_in:
        print(f"✅ 当前登录状态: {loader.context.username}")
    else:
        print("ℹ️  未登录，仅能下载公开内容（推荐使用 --load-cookies edge）")
        if args.stories or args.highlights or args.download_all:
            print("   ⚠️  下载 Stories/Highlights 需要登录，已跳过")
            args.stories = False
            args.highlights = False

    # --all 开关
    if args.download_all:
        args.stories = True
        args.highlights = True
        args.tagged = True
        args.reels = True
        args.igtv = True

    # 逐个下载
    success_count = 0
    failed_count = 0
    total = len(usernames)
    base_done = len(batch_done)
    grand_total = base_done + total
    for i, username in enumerate(usernames, 1):
        print(f"\n{'#'*60}")
        print(f"进度: [{base_done + i}/{grand_total}]")
        print(f"用户: @{username}")

        max_retries = 3
        ok = False
        for retry in range(max_retries):
            try:
                ok = download_profile_content(
                    loader, username,
                    download_stories=args.stories,
                    download_highlights=args.highlights,
                    download_avatar=args.avatar,
                    download_tagged=args.tagged,
                    download_reels=args.reels,
                    download_igtv=args.igtv,
                    fast_update=args.fast_update,
                    fill_gaps=args.fill_gaps,
                    gone_dir=output_dir,
                )
            except instaloader.ConnectionException as e:
                # download_profile_content 内部已捕获大部分异常，这里仅作兜底重试
                if retry < max_retries - 1:
                    wait = (retry + 1) * 60
                    print(f"\n⚠️  连接错误，等待 {wait} 秒后重试 ({retry + 1}/{max_retries})...")
                    print(f"   错误: {str(e)[:100]}")
                    time.sleep(wait)
                    continue
                print(f"\n❌ 重试 {max_retries} 次后仍失败: {str(e)[:150]}")
                ok = False
            except Exception as e:
                print(f"\n❌ 处理 '{username}' 时出错: {e}")
                ok = False
            break

        if ok:
            success_count += 1
            if args.batch_file or args.batch_resume:
                batch_done.append(username)
                try:
                    save_batch_state(state_file, batch_all, batch_done)
                except Exception as e:
                    print(f"⚠️  写入断点状态失败: {e}")
        else:
            failed_count += 1
            print("   ↳ 失败用户不记入断点，下次 --batch-resume 会重新尝试")

    print(f"\n{'='*60}")
    print(f"📊 完成！本次成功: {success_count}/{total}，失败: {failed_count}")
    print(f"   累计进度: {base_done + success_count}/{grand_total}")
    print(f"   输出目录: {output_dir.resolve()}")
    print(f"{'='*60}")

    if args.batch_file or args.batch_resume:
        # 清理状态文件
        if failed_count == 0 and success_count == total:
            try:
                state_file.unlink()
                print("✅ 批量任务全部完成，状态文件已清除")
            except Exception:
                pass
        else:
            remaining = max(grand_total - base_done - success_count, 0)
            print(f"💾 任务未完成，剩余 {remaining} 个；下次可使用 --batch-resume 继续")

    if loader.context.has_stored_errors:
        print("\n⚠️  部分下载出错，请查看上方日志。")
        sys.exit(1)


if __name__ == "__main__":
    main()
