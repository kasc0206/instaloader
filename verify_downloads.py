#!/usr/bin/env python3
"""核验本地下载完整性：把「远端帖子列表」与「本地文件」逐个比对。

为什么需要这个工具：**不能用文件 mtime 判断是否有更新** ——
instaloader 会把媒体文件（.jpg/.mp4）的 mtime 设成帖子发布时间，
只有 `.json.xz` 元数据的 mtime 才是真实写入时间。
按 mtime 统计会严重低估，曾导致误判「已是最新」。

用法::

    python3 verify_downloads.py                    # 核验 download_test 下所有用户
    python3 verify_downloads.py llyrsnsx dodorisyu_  # 只核验指定用户
    python3 verify_downloads.py --limit 30          # 每个用户只比对最近 30 个帖子
    python3 verify_downloads.py --json              # 输出 JSON

退出码：0 = 全部完整；1 = 存在缺失（便于挂到 CI / 定时任务）
"""
import argparse
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import instaloader

from rate_limiter import add_profile_args, get_limiter

DEFAULT_OUTPUT_DIR = "download_test"


def check_user(loader: instaloader.Instaloader, username: str, base_dir: str,
               limit: int):
    """返回 (远端帖子总数, 已比对数, 缺失列表)。"""
    user_dir = os.path.join(base_dir, username)
    if not os.path.isdir(user_dir):
        return None, 0, []
    local = set(os.listdir(user_dir))

    profile = instaloader.Profile.from_username(loader.context, username)
    missing = []
    checked = 0
    for post in itertools.islice(profile.get_posts(), limit):
        checked += 1
        stamp = post.date_utc.strftime("%Y-%m-%d_%H-%M-%S_UTC")
        if not any(f.startswith(stamp) for f in local):
            missing.append({
                "date": post.date_utc.date().isoformat(),
                "shortcode": post.shortcode,
            })
    return profile.mediacount, checked, missing


def main():
    parser = argparse.ArgumentParser(
        description="核验 download_test 中各用户的下载完整性（对比远端帖子列表）")
    parser.add_argument("usernames", nargs="*",
                        help="要核验的用户名（默认：download_test 下所有目录）")
    parser.add_argument("--base-dir", default=DEFAULT_OUTPUT_DIR,
                        help=f"下载根目录（默认 {DEFAULT_OUTPUT_DIR}）")
    parser.add_argument("--limit", type=int, default=20,
                        help="每个用户比对最近多少个帖子（默认 20）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    add_profile_args(parser)
    args = parser.parse_args()

    limiter = get_limiter(profile=args.rate_profile, min_interval=args.min_interval)
    if not args.json:
        print(f"⚙️  {limiter.describe()}")

    usernames = args.usernames
    if not usernames:
        if not os.path.isdir(args.base_dir):
            print(f"❌ 目录不存在: {args.base_dir}")
            return 1
        usernames = sorted(d for d in os.listdir(args.base_dir)
                           if os.path.isdir(os.path.join(args.base_dir, d))
                           and not d.startswith("."))

    loader = instaloader.Instaloader(quiet=True, download_pictures=False,
                                     download_videos=False)
    try:
        loader.load_session_from_file("kasc0206")
    except FileNotFoundError:
        print("⚠️  未找到会话文件，使用匿名访问（部分用户可能不可见）")
        print("   提示：先运行 python3 import_cookies.py")

    results = []
    total_missing = 0
    for username in usernames:
        try:
            total, checked, missing = check_user(loader, username,
                                                 args.base_dir, args.limit)
        except Exception as e:
            results.append({"username": username, "error": f"{type(e).__name__}: {e}"})
            if not args.json:
                print(f"  ❌ {username}: {type(e).__name__}: {e}")
            continue
        if total is None:
            if not args.json:
                print(f"  ⚠️  {username}: 本地无目录，跳过")
            continue
        results.append({
            "username": username, "remote_posts": total,
            "checked": checked, "missing": missing,
        })
        total_missing += len(missing)
        if not args.json:
            mark = "✅" if not missing else "❌"
            detail = "最新" if not missing else f"缺失 {len(missing)}"
            print(f"  {mark} {username:<22} 远端 {total:>5} 帖 | "
                  f"比对最近 {checked:>2} 个 → {detail}")
            for m in missing:
                print(f"        └─ {m['date']}  {m['shortcode']}")

    if args.json:
        print(json.dumps({"results": results, "total_missing": total_missing},
                         ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"核验完成：{len(results)} 个用户，缺失 {total_missing} 个帖子")
        print(f"{'='*60}")
    return 1 if total_missing else 0


if __name__ == "__main__":
    sys.exit(main())
