#!/usr/bin/env python3
"""
分析 Instagram 账号的粉丝和关注数据 (使用 Web API)
"""
import os
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
import instaloader
from instaloader import Profile

BROWSER = "edge"
USERNAME = "chrissylii_"


def load_cookies(loader, browser):
    """从浏览器导入 cookies"""
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
    username = loader.test_login()
    if not username:
        print("❌ 未检测到登录状态")
        sys.exit(1)
    loader.context.username = username
    print(f"✅ 已登录为 {username}")
    return username


def fetch_friendship_via_api(session, user_id, endpoint, max_pages=None,
                             on_progress=None):
    """
    通过 Instagram Web API 获取 followers 或 following。
    endpoint: 'followers' 或 'following'
    on_progress: 回调函数(users_so_far)，可用于增量保存
    """
    cookies_dict = requests.utils.dict_from_cookiejar(session.cookies)
    csrf = cookies_dict.get("csrftoken", "")
    if not csrf:
        session.get("https://www.instagram.com/")
        cookies_dict = requests.utils.dict_from_cookiejar(session.cookies)
        csrf = cookies_dict.get("csrftoken", "")

    headers = {
        "X-CSRFToken": csrf,
        "X-IG-App-ID": "936619743392459",
        "Referer": "https://www.instagram.com/",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
    }

    max_id = None
    users = []
    page_count = 0
    retries_429 = 0
    retries_other = 0
    last_print = 0

    while True:
        params = {"count": 50}
        if max_id:
            params["max_id"] = max_id

        try:
            resp = session.get(
                f"https://www.instagram.com/api/v1/friendships/{user_id}/{endpoint}/",
                params=params,
                headers=headers,
                timeout=30,
            )
        except requests.exceptions.Timeout:
            retries_other += 1
            if retries_other > 2:
                print(f"\n   ⚠️ 请求超时多次，停止获取 (已获取 {len(users)} 个)")
                break
            print(f"\n   ⏳ 请求超时，重试 {retries_other}/2...")
            time.sleep(5)
            continue
        except requests.exceptions.RequestException as e:
            retries_other += 1
            if retries_other > 2:
                print(f"\n   ⚠️ 网络错误: {e}")
                break
            print(f"\n   ⏳ 网络错误，重试 {retries_other}/2...")
            time.sleep(10)
            continue

        retries_other = 0

        if resp.status_code == 429:
            retries_429 += 1
            if retries_429 > 5:
                print(f"\n   ⚠️ 频率限制过多，停止获取 (已获取 {len(users)} 个)")
                break
            wait = 30 * retries_429
            print(f"\n   ⏳ 频率限制 ({retries_429}/5)，等待 {wait}s...", end="", flush=True)
            for s in range(wait):
                time.sleep(1)
                if s % 10 == 9:
                    print(".", end="", flush=True)
            print(" 继续")
            continue
        if resp.status_code != 200:
            print(f"\n   ⚠️ API 返回 {resp.status_code}, 已获取 {len(users)} 个")
            print(f"      响应: {resp.text[:200]}")
            break

        retries_429 = 0
        data = resp.json()
        items = data.get("users", [])
        if not items:
            print("\n   📭 没有更多数据")
            break

        for item in items:
            users.append({
                "pk": item.get("pk"),
                "username": item.get("username"),
                "full_name": item.get("full_name", ""),
                "is_private": item.get("is_private", False),
                "is_verified": item.get("is_verified", False),
                "follower_count": item.get("follower_count", 0) or 0,
                "following_count": item.get("following_count", 0) or 0,
                "media_count": item.get("media_count", 0) or 0,
            })

        page_count += 1
        if len(users) - last_print >= 50:
            print(f"      📦 {endpoint}: 已获取 {len(users)} 个 (第{page_count}页)")
            last_print = len(users)
            if on_progress:
                on_progress(users)

        if max_pages and page_count >= max_pages:
            print(f"   ⏹️ 达到最大页数限制 ({max_pages})")
            break

        next_max_id = data.get("next_max_id")
        if not next_max_id:
            break
        max_id = next_max_id

    return users


def _save_intermediate(output_file, profile, user_id, followees, followers):
    """增量保存数据到 JSON"""
    output_data = {
        "profile": {"username": profile.username, "userid": user_id,
                     "followers_count": profile.followers, "followees_count": profile.followees},
        "followees": followees,
        "followers": followers,
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)


def main():
    loader = instaloader.Instaloader(
        quiet=True,
        download_pictures=False,
        download_videos=False,
    )

    load_cookies(loader, BROWSER)

    profile = Profile.from_username(loader.context, USERNAME)
    user_id = profile.userid
    print(f"\n{'='*60}")
    print(f"📊 账号分析: {profile.username} (ID: {user_id})")
    print(f"   全名: '{profile.full_name}'")
    print(f"   粉丝数: {profile.followers:,}")
    print(f"   关注数: {profile.followees:,}")
    print(f"   帖子数: {profile.mediacount}")
    print(f"   私密账号: {'是' if profile.is_private else '否'}")
    print(f"{'='*60}\n")

    session = loader.context._session

    # ===== 1. 获取关注列表 =====
    print("📋 [1/2] 正在获取关注列表（following）...")
    followees = fetch_friendship_via_api(session, user_id, "following")
    print(f"\n✅ 获取到 {len(followees)} 个关注")

    # ===== 2. 获取粉丝列表 =====
    output_file = f"{USERNAME}_analysis.json"

    # 先保存关注数据
    _save_intermediate(output_file, profile, user_id, followees, [])

    print(f"\n📋 [2/2] 正在获取粉丝列表（followers, 共 {profile.followers:,}）...")

    def _on_followers_progress(users_so_far):
        _save_intermediate(output_file, profile, user_id, followees, users_so_far)

    followers = fetch_friendship_via_api(session, user_id, "followers",
                                         max_pages=200,
                                         on_progress=_on_followers_progress)
    print(f"\n✅ 获取到 {len(followers)} 个粉丝")

    # ===== 3. 最终保存 =====
    _save_intermediate(output_file, profile, user_id, followees, followers)
    print(f"💾 数据已保存到 {output_file}")

    # ===== 4. 关注分析 =====
    print(f"\n{'='*60}")
    print(f"📋 【关注分析】共 {len(followees)} 人")
    print(f"{'='*60}")

    if followees:
        s = sorted(followees, key=lambda x: x["follower_count"], reverse=True)
        print("\n📊 TOP 30 关注（按粉丝数）:")
        print(f"{'#':>3} | {'用户名':<22} | {'粉丝':>10} | {'关注':>8} | {'帖子':>6} | {'私密':>4} | {'认证':>4}")
        print("-" * 65)
        for i, f in enumerate(s[:30]):
            print(f"{i+1:>3} | {f['username']:<22} | {f['follower_count']:>10,} | {f['following_count']:>8,} | {f['media_count']:>6} | {'🔒' if f['is_private'] else '公开':>4} | {'✅' if f['is_verified'] else '':>4}")

        pv = sum(1 for f in followees if f["is_private"])
        vf = sum(1 for f in followees if f["is_verified"])
        avg_f = sum(f["follower_count"] for f in followees) / len(followees)
        print(f"\n📊 关注统计: 私密{pv}({pv/len(followees)*100:.1f}%) | 认证{vf}({vf/len(followees)*100:.1f}%) | 平均粉丝{avg_f:,.0f}")

        print("\n📊 粉丝数分布:")
        for lo, hi, lb in [(0,100,"<100"),(100,1000,"100~1k"),(1000,10000,"1k~1万"),(10000,100000,"1万~10万"),(100000,1000000,"10万~100万"),(1000000,999999999,">100万")]:
            c = sum(1 for f in followees if lo <= f["follower_count"] < hi)
            if c:
                print(f"   {lb:<12}: {c:>3} ({c/len(followees)*100:>4.1f}%)")

    # ===== 5. 粉丝分析 =====
    print(f"\n{'='*60}")
    print(f"📋 【粉丝分析】共 {len(followers)} 人（总粉丝{profile.followers:,}）")
    print(f"{'='*60}")

    if followers:
        s = sorted(followers, key=lambda x: x["follower_count"], reverse=True)
        print("\n📊 TOP 30 粉丝（按粉丝数）:")
        print(f"{'#':>3} | {'用户名':<22} | {'粉丝':>10} | {'关注':>8} | {'帖子':>6} | {'私密':>4} | {'认证':>4}")
        print("-" * 65)
        for i, f in enumerate(s[:30]):
            print(f"{i+1:>3} | {f['username']:<22} | {f['follower_count']:>10,} | {f['following_count']:>8,} | {f['media_count']:>6} | {'🔒' if f['is_private'] else '公开':>4} | {'✅' if f['is_verified'] else '':>4}")

        pv = sum(1 for f in followers if f["is_private"])
        vf = sum(1 for f in followers if f["is_verified"])
        avg_f = sum(f["follower_count"] for f in followers) / len(followers)
        print(f"\n📊 粉丝统计: 私密{pv}({pv/len(followers)*100:.1f}%) | 认证{vf}({vf/len(followers)*100:.1f}%) | 平均粉丝{avg_f:,.0f}")

        print("\n📊 粉丝分类:")
        big = [f for f in followers if f["follower_count"] >= 100000]
        mid = [f for f in followers if 1000 <= f["follower_count"] < 100000]
        sml = [f for f in followers if f["follower_count"] < 1000]
        print(f"   🌟 大V (>10万): {len(big)} ({len(big)/len(followers)*100:.1f}%)")
        print(f"   📱 活跃 (1k~10万): {len(mid)} ({len(mid)/len(followers)*100:.1f}%)")
        print(f"   🔰 小号 (<1k): {len(sml)} ({len(sml)/len(followers)*100:.1f}%)")

        # ===== 6. 相互关注 =====
        fu = {f["username"] for f in followees}
        mutual = [f for f in followers if f["username"] in fu]
        if mutual:
            print(f"\n🔄 相互关注: {len(mutual)} 人")
            print(f"{'#':>3} | {'用户名':<22} | {'粉丝':>10} | {'关注':>8}")
            print("-" * 50)
            for i, f in enumerate(sorted(mutual, key=lambda x: x["follower_count"], reverse=True)):
                print(f"{i+1:>3} | {f['username']:<22} | {f['follower_count']:>10,} | {f['following_count']:>8,}")

        # ===== 7. 关注了但没回关 =====
        fl = {f["username"] for f in followers}
        not_back = [f for f in followees if f["username"] not in fl]
        if not_back:
            print(f"\n👀 单向关注（对方没回关）: {len(not_back)} 人")
            print(f"{'#':>3} | {'用户名':<22} | {'粉丝':>10} | {'关注':>8}")
            print("-" * 50)
            for i, f in enumerate(sorted(not_back, key=lambda x: x["follower_count"], reverse=True)[:20]):
                print(f"{i+1:>3} | {f['username']:<22} | {f['follower_count']:>10,} | {f['following_count']:>8,}")
            if len(not_back) > 20:
                print(f"   ... 还有 {len(not_back) - 20} 人")

    print(f"\n{'='*60}")
    print(f"✅ 分析完成！数据已保存到 {output_file}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
