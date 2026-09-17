#!/usr/bin/env python3
"""
从浏览器导入 Instagram Cookies（刷新登录状态）
================================================
从 Edge / Chrome / Firefox 等浏览器读取 instagram.com 的 cookies，
校验登录状态，并保存为 Instaloader 会话文件，供后续脚本复用。

用法:
  # 从 Edge 导入（默认）
  python3 import_cookies.py

  # 指定浏览器
  python3 import_cookies.py --browser chrome

  # 触发频率限制时跳过登录验证（仅导入 cookies，不联网校验）
  python3 import_cookies.py --skip-check

  # 额外导出一份 Netscape 格式的 cookies 文本文件
  python3 import_cookies.py --save-raw

注意（macOS）:
  Edge 的 Cookies 数据库受 Keychain 加密保护。首次运行可能弹出
  "Microsoft Edge Safe Storage" 授权框，请输入本机登录密码并选择“始终允许”。
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import instaloader
from instaloader.instaloader import get_default_session_filename

SUPPORTED_BROWSERS = [
    "brave",
    "chrome",
    "chromium",
    "edge",
    "firefox",
    "librewolf",
    "opera",
    "opera_gx",
    "safari",
    "vivaldi",
]

# test_login 触发频率限制时的重试次数与间隔
LOGIN_RETRIES = 3
RETRY_WAIT = 30


def get_browser_loader(browser: str):
    """返回 browser_cookie3 中对应浏览器的读取函数"""
    try:
        import browser_cookie3
    except ImportError:
        print("❌ 请先安装 browser_cookie3: python3 -m pip install browser_cookie3")
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
    return browser_map[browser.lower()]


def read_cookies(browser: str) -> dict:
    """从浏览器读取 instagram.com 的 cookies"""
    loader_fn = get_browser_loader(browser)

    print(f"🔑 正在从 {browser} 读取 Instagram cookies...")
    try:
        jar = loader_fn(domain_name="instagram.com")
    except Exception as e:
        print(f"❌ 读取 {browser} cookies 失败: {type(e).__name__}: {e}")
        print("   macOS 常见原因：Keychain 授权被拒绝，或数据库被加密保护。")
        print("   解决：重新运行并在弹窗中输入本机密码，选择“始终允许”。")
        print(f"   若仍失败，请先在 {browser} 中打开并登录 https://www.instagram.com/")
        sys.exit(1)

    cookies = {}
    for cookie in jar:
        if "instagram.com" in (cookie.domain or ""):
            cookies[cookie.name] = cookie.value

    if not cookies:
        print(f"❌ 在 {browser} 中未找到 Instagram cookies。")
        print(f"   请先在 {browser} 中打开并登录 https://www.instagram.com/ ，再重试。")
        sys.exit(1)

    return cookies


def export_netscape(cookies: dict, path: str) -> None:
    """导出为 Netscape 格式的 cookies 文本文件"""
    expires = int(time.time()) + 365 * 24 * 3600
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for name, value in cookies.items():
            f.write(
                "\t".join(
                    [
                        ".instagram.com",
                        "TRUE",
                        "/",
                        "TRUE",
                        str(expires),
                        name,
                        value,
                    ]
                )
                + "\n"
            )
    print(f"📄 已导出 cookies 文本文件: {path}")


def main():
    parser = argparse.ArgumentParser(
        description="从浏览器导入 Instagram cookies 并保存 Instaloader 会话",
    )
    parser.add_argument(
        "--browser",
        "-b",
        default="edge",
        choices=SUPPORTED_BROWSERS,
        help="浏览器（默认 edge）",
    )
    parser.add_argument(
        "--skip-check",
        action="store_true",
        help="跳过登录验证（触发频率限制时使用，直接用 cookies 保存会话）",
    )
    parser.add_argument(
        "--save-raw",
        action="store_true",
        help="额外导出 Netscape 格式的 cookies 文本文件",
    )
    parser.add_argument(
        "--save-session",
        default=None,
        help="指定会话文件路径（默认 ~/.config/instaloader/session-<用户名>）",
    )
    args = parser.parse_args()

    cookies = read_cookies(args.browser)
    print(
        f"✅ 已读取 {len(cookies)} 个 cookies"
        f"（{'含 sessionid' if 'sessionid' in cookies else '⚠️ 无 sessionid，可能未登录'}）"
    )

    loader = instaloader.Instaloader(
        quiet=True,
        download_pictures=False,
        download_videos=False,
    )
    loader.context.update_cookies(cookies)

    # ===== 校验登录状态 =====
    username = None
    if args.skip_check:
        # 无法联网校验时，只能依赖 cookie 里的用户名信息
        username = cookies.get("ds_user") or None
        if username:
            print(f"⚠️  已跳过登录验证，从 cookie 推断用户名: {username}")
        else:
            print("⚠️  已跳过登录验证，且 cookie 中无用户名（ds_user）")
    else:
        for attempt in range(1, LOGIN_RETRIES + 1):
            try:
                username = loader.test_login()
            except instaloader.ConnectionException as e:
                print(f"❌ 登录校验失败: {str(e)[:160]}")
                sys.exit(1)
            except Exception as e:
                print(f"❌ 登录校验异常: {type(e).__name__}: {e}")
                sys.exit(1)

            if username:
                break
            if attempt < LOGIN_RETRIES:
                print(
                    f"⏳ 未检测到登录状态（可能触发频率限制），"
                    f"{RETRY_WAIT}s 后重试 ({attempt}/{LOGIN_RETRIES - 1})..."
                )
                time.sleep(RETRY_WAIT)

        if not username:
            print("❌ cookies 已读取，但未检测到登录状态。")
            print(f"   请在 {args.browser} 中重新登录 Instagram 后再试，")
            print("   或用 --skip-check 强制导入（不推荐，后续请求可能仍被拒）。")
            sys.exit(1)

    if username:
        loader.context.username = username
        print(f"✅ 登录状态有效: {username}")

    # ===== 保存会话文件 =====
    session_path = args.save_session
    if session_path is None and username:
        session_path = get_default_session_filename(username)

    if session_path is None:
        # --skip-check 且 cookie 中没有用户名：会话文件名无从推断
        print("⚠️  无法确定用户名，跳过保存会话文件。")
        print(
            "   如需保存，请指定路径：--save-session ~/.config/instaloader/session-<用户名>"
        )
    else:
        try:
            os.makedirs(os.path.dirname(session_path), exist_ok=True)
            loader.save_session_to_file(session_path)
            print(f"💾 会话已保存: {session_path}")
        except Exception as e:
            print(f"⚠️ 保存会话失败: {type(e).__name__}: {e}")

    # ===== 可选：导出原始 cookies =====
    if args.save_raw:
        raw_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"cookies_{username or 'imported'}.txt",
        )
        try:
            export_netscape(cookies, raw_path)
        except Exception as e:
            print(f"⚠️ 导出 cookies 失败: {type(e).__name__}: {e}")

    print("\n✅ 完成，后续脚本可直接复用该会话 / cookies。")


if __name__ == "__main__":
    main()
