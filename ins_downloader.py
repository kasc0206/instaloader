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

import os
import re
import sys
import json
import time
import argparse
import getpass
from pathlib import Path
from typing import List

# 确保可以找到本地修改后的 instaloader 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import instaloader
from instaloader import Profile, ProfileNotExistsException


# 支持的浏览器列表
SUPPORTED_BROWSERS = ["brave", "chrome", "chromium", "edge", "firefox",
                       "librewolf", "opera", "opera_gx", "safari", "vivaldi"]


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


def load_cookies_from_browser(loader: instaloader.Instaloader, browser: str):
    """从浏览器导入 Instagram cookies"""
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
        username = loader.test_login()
        if not username:
            print(f"❌ cookies 导入成功但未检测到登录状态，请重新在 {browser} 中登录 Instagram。")
            sys.exit(1)

        loader.context.username = username
        print(f"✅ 已通过 {browser} 登录为 {username}")

        # 保存 session 文件供后续使用
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
                              fast_update: bool = False) -> None:
    """下载指定用户的所有内容"""
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
        try:
            loader.download_profile(profile, profile_pic=False, fast_update=fast_update)
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

    except ProfileNotExistsException:
        print(f"❌ 用户 '{username}' 不存在")
    except instaloader.PrivateProfileNotFollowedException:
        print(f"❌ 用户 '{username}' 是私密账号，你的账号未关注该用户")
    except instaloader.LoginRequiredException:
        print(f"❌ 需要登录才能访问 '{username}' 的内容")
    except instaloader.ConnectionException as e:
        error_msg = str(e)
        if "403" in error_msg:
            print(f"⚠️ 用户 '{username}' API 限制 (403 Forbidden)")
            print(f"   Instagram 临时限制了对该用户的访问，可稍后重试")
            print(f"   💡 单独重试: python3 ins_downloader.py --load-cookies edge --url {username} --fast")
        elif "429" in error_msg:
            print(f"⏳ 用户 '{username}' 触发频率限制 (429)")
            print(f"   请等待几分钟后再试")
        else:
            print(f"❌ 连接错误: {e}")
    except Exception as e:
        print(f"❌ 下载 '{username}' 时发生未知错误: {e}")


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
                                help="快速模式，只下载新内容")
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
            for entry in sorted(output_dir.iterdir()):
                if entry.is_dir() and not entry.name.startswith('.'):
                    usernames.append(entry.name)
            if usernames:
                print(f"🔄 更新模式：扫描到 {len(usernames)} 个已下载的用户")
            else:
                print(f"❌ 输出目录 '{output_dir}' 中未找到已下载的用户")
                sys.exit(1)
        else:
            print(f"❌ 输出目录 '{output_dir}' 不存在")
            sys.exit(1)
        # 更新模式默认使用快速模式
        args.fast_update = True
        # 更新模式只下载头像 + 帖子（跳过 Stories/Highlights/Tagged/Reels/IGTV
        # 因为这些内容依赖的 graphql/query 接口容易被 Instagram 限制）
        args.download_all = False
        args.avatar = True
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
    resume_index = 0
    state_file = output_dir / ".batch_state.json"
    if args.batch_file or args.batch_resume:
        usernames = []  # 清空，batch 模式独立处理
        if args.batch_resume:
            # 恢复模式：从 state 文件中读取
            if not state_file.exists():
                print(f"❌ 未找到断点状态文件 {state_file}，无法恢复")
                sys.exit(1)
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                usernames = state['pending']
                resume_index = state.get('index', 0)
                completed = state.get('completed', [])
                print(f"🔄 恢复上次任务：已完成 {len(completed)} 个，待下载 {len(usernames)} 个")
                if completed:
                    print(f"   已完成的用户: {', '.join(completed[-5:])}...")
                if usernames:
                    print(f"   从第 {resume_index + 1} 个开始: @{usernames[0]}")
            except Exception as e:
                print(f"❌ 读取状态文件失败: {e}")
                sys.exit(1)
        else:
            # 首次批量模式：读取用户列表文件
            try:
                with open(args.batch_file, 'r') as f:
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

            # 保存初始状态
            state = {'index': 0, 'completed': [], 'pending': usernames}
            with open(state_file, 'w') as f:
                json.dump(state, f, ensure_ascii=False)

        # 批量模式默认使用快速模式+头像
        if not args.stories and not args.highlights and not args.tagged \
                and not args.reels and not args.igtv and not args.download_all:
            args.fast_update = True
            args.avatar = True
        usernames = usernames[resume_index:]
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
    )

    # 登录方式
    if args.browser:
        # 方式1: 从浏览器导入 cookies（推荐）
        load_cookies_from_browser(loader, args.browser)

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
    total = len(usernames)
    for i, username in enumerate(usernames, 1):
        actual_idx = resume_index + i
        print(f"\n{'#'*60}")
        print(f"进度: [{actual_idx}/{total if not args.batch_file else total + resume_index}]")
        print(f"用户: @{username}")
        max_retries = 3
        for retry in range(max_retries):
            try:
                download_profile_content(
                    loader, username,
                    download_stories=args.stories,
                    download_highlights=args.highlights,
                    download_avatar=args.avatar,
                    download_tagged=args.tagged,
                    download_reels=args.reels,
                    download_igtv=args.igtv,
                    fast_update=args.fast_update,
                )
                success_count += 1
                # 更新批量状态
                if args.batch_file or args.batch_resume:
                    try:
                        with open(state_file, 'r') as f:
                            state = json.load(f)
                        state['completed'].append(username)
                        state['pending'] = usernames[i:] if i < len(usernames) else []
                        state['index'] = actual_idx
                        with open(state_file, 'w') as f:
                            json.dump(state, f, ensure_ascii=False)
                    except Exception:
                        pass
                break
            except instaloader.ConnectionException as e:
                error_msg = str(e)
                if retry < max_retries - 1:
                    print(f"\n⚠️  连接错误，等待 {(retry + 1) * 60} 秒后重试 ({retry + 1}/{max_retries})...")
                    print(f"   错误: {error_msg[:100]}")
                    time.sleep((retry + 1) * 60)
                else:
                    print(f"\n❌ 重试 {max_retries} 次后仍失败: {error_msg[:150]}")
            except Exception as e:
                print(f"\n❌ 处理 '{username}' 时出错: {e}")
                break

    print(f"\n{'='*60}")
    total_all = total + resume_index
    print(f"📊 完成！成功: {success_count}/{total_all}")
    print(f"   输出目录: {output_dir.resolve()}")
    print(f"{'='*60}")

    if args.batch_file or args.batch_resume:
        # 清理状态文件
        if success_count == total:
            try:
                state_file.unlink()
                print("✅ 批量任务全部完成，状态文件已清除")
            except Exception:
                pass
        else:
            print(f"💾 任务未完成，下次可使用 --batch-resume 继续")

    if loader.context.has_stored_errors:
        print("\n⚠️  部分下载出错，请查看上方日志。")
        sys.exit(1)


if __name__ == "__main__":
    main()
