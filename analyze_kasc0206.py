#!/usr/bin/env python3
"""
分析 kasc0206 关注的用户

用法:
  # 首次运行：获取关注列表 + 尝试获取详情
  python3 analyze_kasc0206.py

  # 断点续传：每次获取 25 个详情（配合 --auto 自动循环）
  python3 analyze_kasc0206.py --resume

  # 自动模式：每隔 5~8 分钟获取一批，每批 25 个
  python3 analyze_kasc0206.py --auto
"""
import os
import sys
import time
import json
import random
import argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
import instaloader
from instaloader import Profile

BROWSER = "edge"
USERNAME = "kasc0206"
OUTPUT_FILE = f"{USERNAME}_analysis.json"
BATCH_SIZE = 25
MIN_DELAY = 300    # 5 分钟
MAX_DELAY = 480    # 8 分钟


def load_cookies(loader, browser, skip_login_check=False):
    import browser_cookie3
    browser_map = {
        "edge": browser_cookie3.edge,
        "chrome": browser_cookie3.chrome,
        "firefox": browser_cookie3.firefox,
    }
    print(f"🔑 正在从 {browser} 导入 cookies...")
    cookies = {}
    for cookie in browser_map[browser](domain_name="instagram.com"):
        if "instagram.com" in cookie.domain:
            cookies[cookie.name] = cookie.value
    if not cookies:
        print("❌ 未找到 cookies")
        sys.exit(1)
    loader.context.update_cookies(cookies)
    if skip_login_check:
        loader.context.username = "kasc0206"
        print("✅ Cookies 已导入（跳过登录验证）")
        return "kasc0206"
    username = loader.test_login()
    if not username:
        print("❌ 未检测到登录状态")
        print("   可能是触发了频率限制，请等待几分钟后重试")
        print("   或尝试: python3 analyze_kasc0206.py --resume --skip-check")
        sys.exit(1)
    loader.context.username = username
    print(f"✅ 已登录为 {username}")
    return username


def get_api_headers(session):
    cookies_dict = requests.utils.dict_from_cookiejar(session.cookies)
    csrf = cookies_dict.get("csrftoken", "")
    if not csrf:
        session.get("https://www.instagram.com/")
        cookies_dict = requests.utils.dict_from_cookiejar(session.cookies)
        csrf = cookies_dict.get("csrftoken", "")
    return {
        "X-CSRFToken": csrf,
        "X-IG-App-ID": "936619743392459",
        "Referer": "https://www.instagram.com/",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
    }


def fetch_following(session, user_id):
    """获取关注列表"""
    headers = get_api_headers(session)
    max_id = None
    users = []
    page_count = 0
    retries = 0

    while True:
        params = {"count": 50}
        if max_id:
            params["max_id"] = max_id

        try:
            resp = session.get(
                f"https://www.instagram.com/api/v1/friendships/{user_id}/following/",
                params=params, headers=headers, timeout=30,
            )
        except requests.exceptions.RequestException as e:
            retries += 1
            if retries > 2:
                print(f"\n   ⚠️ 请求失败: {e}")
                break
            time.sleep(5)
            continue

        retries = 0

        if resp.status_code == 429:
            print("\n   ⏳ 频率限制，等待 30s...")
            time.sleep(30)
            continue
        if resp.status_code != 200:
            print(f"\n   ⚠️ API 返回 {resp.status_code}, 已获取 {len(users)} 个")
            break

        data = resp.json()
        items = data.get("users", [])
        if not items:
            break

        for item in items:
            users.append({
                "pk": item.get("pk"),
                "username": item.get("username"),
                "full_name": item.get("full_name", ""),
                "is_private": item.get("is_private", False),
                "is_verified": item.get("is_verified", False),
            })

        page_count += 1
        if len(users) % 50 == 0:
            print(f"      📦 已获取 {len(users)} 个 (第{page_count}页)")

        next_max_id = data.get("next_max_id")
        if not next_max_id:
            break
        max_id = next_max_id

    return users


def fetch_profile_details_via_api(session, username):
    """通过 Instagram Web API 获取单个用户的详细资料"""
    headers = get_api_headers(session)
    try:
        resp = session.get(
            f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}",
            headers=headers, timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            user = data.get("data", {}).get("user", {})
            if user:
                return {
                    "follower_count": user.get("edge_followed_by", {}).get("count", 0),
                    "following_count": user.get("edge_follow", {}).get("count", 0),
                    "media_count": user.get("edge_owner_to_timeline_media", {}).get("count", 0),
                    "full_name": user.get("full_name", ""),
                    "is_private": user.get("is_private", False),
                    "is_verified": user.get("is_verified", False),
                    "biography": (user.get("biography", "") or "")[:100],
                    "external_url": user.get("external_url", "") or "",
                }
        return None
    except Exception:
        return None


def save_data(followees_data, profile_data, stats_note=""):
    """保存数据到 JSON 文件"""
    output = {
        "profile": profile_data,
        "stats_note": stats_note,
        "followees": followees_data,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


def load_existing():
    """加载已保存的数据"""
    if not os.path.exists(OUTPUT_FILE):
        print(f"❌ 未找到 {OUTPUT_FILE}，请先首次运行")
        sys.exit(1)
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        return json.load(f)


def find_pending_users(data):
    """找出还没有详细信息的用户（按原顺序返回）"""
    pending = []
    for i, u in enumerate(data["followees"]):
        if not u.get("follower_count"):  # 0 or missing = 未获取
            pending.append((i, u))
    return pending


def do_batch(session, data, batch_size=BATCH_SIZE):
    """获取下一批用户的详细信息，返回 (成功数, 总完成数, 总待处理数)"""
    pending = find_pending_users(data)
    if not pending:
        print("✅ 所有用户的详情已获取完毕！")
        return 0, len(data["followees"]), 0

    batch = pending[:batch_size]
    success = 0
    total_done = len(data["followees"]) - len(pending) + success
    total_left = len(pending)

    print(f"\n📋 本轮目标: {len(batch)} 个用户 (已完成 {total_done - success}，剩余 {total_left})")

    for idx, (orig_idx, user) in enumerate(batch):
        uname = user["username"]
        sys.stdout.write(f"\r   [{idx+1}/{len(batch)}] @{uname:<25} 本轮成功:{success}")
        sys.stdout.flush()

        detail = fetch_profile_details_via_api(session, uname)
        if detail:
            data["followees"][orig_idx].update(detail)
            success += 1
            time.sleep(0.5)
        else:
            # 失败的可能原因：私密账号无权查看 / API限制 / 网络
            time.sleep(1.5)

    total_done = len(data["followees"]) - len(pending) + success
    total_left = len(pending) - len(batch)
    print(f"\n   ✅ 本轮成功: {success}/{len(batch)}，累计完成: {total_done}，剩余: {total_left}")

    return success, total_done, total_left


def print_report(data):
    """打印分析报告"""
    enriched = data["followees"]
    print(f"\n{'='*60}")
    print(f"📋 【kasc0206 关注分析】共 {len(enriched)} 人")
    print(f"{'='*60}")

    with_stats = [f for f in enriched if f.get("follower_count", 0) > 0]
    has_detail_info = len(with_stats) > 0

    if has_detail_info:
        by_followers = sorted(enriched, key=lambda x: x.get("follower_count", 0), reverse=True)
    else:
        by_followers = enriched

    pv = sum(1 for f in enriched if f["is_private"])
    vf = sum(1 for f in enriched if f["is_verified"])

    print("\n📊 基本信息统计:")
    print(f"   总关注数: {len(enriched)}")
    print(f"   已有详情: {len(with_stats)}")
    print(f"   私密账号: {pv} ({pv/len(enriched)*100:.1f}%)")
    print(f"   认证账号: {vf} ({vf/len(enriched)*100:.1f}%)")

    if has_detail_info:
        users_w_stats = [f for f in enriched if f.get("follower_count", 0) > 0]
        avg_f = sum(f.get("follower_count", 0) for f in users_w_stats) / len(users_w_stats)
        total_followers = sum(f.get("follower_count", 0) for f in enriched)

        print(f"   已有详情用户的平均粉丝: {avg_f:,.0f}")
        print(f"   粉丝总和（含为0的）: {total_followers:,}")

        print("\n📊 TOP 20 关注（按粉丝数）:")
        print(f"{'#':>3} | {'用户名':<22} | {'粉丝':>10} | {'关注':>8} | {'帖子':>6} | {'私密':>4} | {'认证':>4}")
        print("-" * 60)
        for i, f in enumerate(by_followers[:20]):
            print(f"{i+1:>3} | @{f['username']:<20} | {f.get('follower_count',0):>10,} | {f.get('following_count',0):>8,} | {f.get('media_count',0):>6} | {'🔒' if f['is_private'] else '公开':>4} | {'✅' if f['is_verified'] else '':>4}")

        big_v = [f for f in enriched if f.get("follower_count", 0) >= 100000]
        if big_v:
            print(f"\n🌟 大V账号 (>10万粉丝): {len(big_v)} 人")
            for f in sorted(big_v, key=lambda x: x.get("follower_count", 0), reverse=True):
                print(f"   @{f['username']:<22} {f.get('follower_count',0):>10,}粉丝 {'🔒' if f['is_private'] else '公开'} {'✅' if f['is_verified'] else ''}")

    no_stats = [f for f in enriched if not f.get("follower_count")]
    if no_stats:
        print(f"\n⏳ 等待获取详情（共 {len(no_stats)} 人）:")
        for i, f in enumerate(no_stats[:20]):
            print(f"   {i+1:>3}. @{f['username']:<25} {'🔒' if f['is_private'] else '公开':>4} {'✅' if f['is_verified'] else '':>4}")
        if len(no_stats) > 20:
            print(f"   ... 还有 {len(no_stats) - 20} 人")

    print(f"\n{'='*60}")


def run_full_scan(skip_check=False):
    """首次完整扫描：获取关注列表 + 尝试获取详情"""
    loader = instaloader.Instaloader(
        quiet=True,
        download_pictures=False,
        download_videos=False,
    )
    load_cookies(loader, BROWSER, skip_login_check=skip_check)

    profile = Profile.from_username(loader.context, USERNAME)
    user_id = profile.userid
    profile_data = {
        "username": profile.username,
        "userid": user_id,
        "followers_count": profile.followers,
        "followees_count": profile.followees,
    }

    print(f"\n{'='*60}")
    print(f"📊 账号: {profile.username} | 关注 {profile.followees} 人 | 粉丝 {profile.followers}")
    print(f"{'='*60}\n")

    session = loader.context._session

    # 获取关注列表
    print("📋 正在获取关注列表...")
    followees = fetch_following(session, user_id)
    print(f"\n✅ 获取到 {len(followees)} 个关注")
    if not followees:
        return

    # 保存基础数据
    save_data(followees, profile_data, "基础数据（无粉丝数详情）")
    print(f"💾 已保存到 {OUTPUT_FILE}")

    # 尝试获取一批详情
    print("\n📋 正在尝试获取首批详情...")
    data = load_existing()
    success, done, left = do_batch(session, data, BATCH_SIZE)
    save_data(data["followees"], profile_data, f"首次扫描（{done} 个有详情）")
    print(f"💾 已保存，{done} 个有详情，剩余 {left} 个")

    print_report(data)

    if left > 0:

        print(f"\n💡 提示: 剩余 {left} 个用户待获取")
        print("   运行以下命令继续获取下一批:")
        print("   python3 analyze_kasc0206.py --resume")
        print("   或自动循环模式:")
        print("   python3 analyze_kasc0206.py --auto")


def run_resume(auto_mode=False, skip_check=False):
    """断点续传：加载已有数据，获取下一批详情"""
    loader = instaloader.Instaloader(
        quiet=True,
        download_pictures=False,
        download_videos=False,
    )
    load_cookies(loader, BROWSER, skip_login_check=skip_check)

    session = loader.context._session

    data = load_existing()
    profile_data = data.get("profile", {})

    pending = find_pending_users(data)
    if not pending:
        print("✅ 所有用户详情已获取完毕！")
        print_report(data)
        return

    done_count = len(data["followees"]) - len(pending)
    print(f"\n📊 进度: {done_count}/{len(data['followees'])} 已完成，剩余 {len(pending)} 个")

    success, total_done, total_left = do_batch(session, data, BATCH_SIZE)

    note = f"断点续传（{total_done}/{len(data['followees'])} 个有详情）"
    save_data(data["followees"], profile_data, note)
    print(f"💾 已保存到 {OUTPUT_FILE}")

    # 打印简短报告
    with_stats = [f for f in data["followees"] if f.get("follower_count", 0) > 0]
    print(f"\n📊 当前进度: {total_done}/{len(data['followees'])} ({total_done/len(data['followees'])*100:.1f}%)")
    print(f"   已有详情: {len(with_stats)} 人")

    if total_left > 0:
        if auto_mode:
            wait = random.randint(MIN_DELAY, MAX_DELAY)
            mins = wait // 60
            secs = wait % 60
            print(f"\n⏳ 等待 {mins} 分 {secs} 秒后继续下一批...")
            for remaining in range(wait, 0, -1):
                mins_left = remaining // 60
                secs_left = remaining % 60
                sys.stdout.write(f"\r   下次获取倒计时: {mins_left:02d}:{secs_left:02d}")
                sys.stdout.flush()
                time.sleep(1)
            print("\n")

            # 递归调用（自动模式，即本函数自己）
            # 但为避免递归过深，用循环替代
            # 这里返回后由 run_auto 的循环处理
            return True  # 信号量：还有剩余，继续
        else:
            print(f"\n💡 剩余 {total_left} 个，下次运行:")
            print("   python3 analyze_kasc0206.py --resume")
    else:
        print("\n🎉 全部完成！")
        print_report(data)

    return False  # 信号量：全部完成


def run_auto(skip_check=False):
    """自动循环模式：不断 --resume，每批间隔 5~8 分钟"""
    print(f"{'='*60}")
    print("🤖 自动批量获取模式")
    print(f"   每批 {BATCH_SIZE} 个，间隔 {MIN_DELAY//60}~{MAX_DELAY//60} 分钟")
    print(f"{'='*60}")

    round_num = 1
    while True:
        print(f"\n{'─'*60}")
        print(f"📌 第 {round_num} 轮")
        print(f"{'─'*60}")

        has_more = run_resume(auto_mode=True, skip_check=skip_check)

        if not has_more:
            print("\n🎉 所有数据获取完成！")
            break

        round_num += 1
        wait = random.randint(MIN_DELAY, MAX_DELAY)
        mins = wait // 60
        secs = wait % 60
        print(f"\n⏳ 第 {round_num} 轮等待 {mins} 分 {secs} 秒...")


def main():
    parser = argparse.ArgumentParser(description="分析 kasc0206 关注的用户")
    parser.add_argument("--resume", action="store_true",
                        help="断点续传模式：加载已有数据，获取下一批详情")
    parser.add_argument("--auto", action="store_true",
                        help="自动模式：每隔 5~8 分钟获取一批，每批 25 个")
    parser.add_argument("--batch-size", type=int, default=25,
                        help="每批数量（默认 25）")
    parser.add_argument("--skip-check", action="store_true",
                        help="跳过登录验证（触发频率限制时使用）")
    args = parser.parse_args()

    global BATCH_SIZE
    BATCH_SIZE = args.batch_size

    if args.auto:
        run_auto(skip_check=args.skip_check)
    elif args.resume:
        run_resume(skip_check=args.skip_check)
    else:
        run_full_scan(skip_check=args.skip_check)


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
