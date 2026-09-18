#!/usr/bin/env python3
"""
🔥 极端稳健的 Instagram 粉丝采集器
- 断点续传（保存 cursor）
- 保守的速率控制
- 可长时间运行
"""
import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests

import instaloader
from instaloader import Profile

BROWSER = "edge"
USERNAME = "chrissylii_"
STATE_FILE = f"{USERNAME}_fetch_state.json"
DATA_FILE = f"{USERNAME}_all_followers.json"
TOTAL_FOLLOWERS = 543262  # 已知总数
BATCH_SIZE = 50
SAVE_INTERVAL = 10  # 每10页保存一次
RATE_LIMIT_WAIT = 60  # 遇到429的基础等待秒数
NORMAL_DELAY = 2.0  # 正常请求间延迟(秒)
MAX_CONSEC_429 = 5  # 连续 429 达到此次数就保存退出，避免无限等待（进度已落盘）

# 全局变量用于信号处理
stop_flag = False

def signal_handler(sig, frame):
    global stop_flag
    print("\n\n⏹️  收到停止信号，正在保存进度...")
    stop_flag = True

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def load_state():
    """加载断点状态"""
    state = {"max_id": None, "count": 0, "page": 0, "users": []}
    # 尝试从数据文件加载已获取的用户
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            state["users"] = json.load(f)
        state["count"] = len(state["users"])
    # 从状态文件加载 cursor
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            meta = json.load(f)
        state["max_id"] = meta.get("max_id")
        state["page"] = meta.get("page", 0)
        print(f"📂 找到断点: 已获取 {state['count']} 个, 进度 {state['count'] / TOTAL_FOLLOWERS * 100:.2f}%")
    else:
        print("📂 无断点，从头开始")
    return state


def save_state(state):
    """保存断点状态（含用户数据）"""
    # 保存状态文件（轻量）
    with open(STATE_FILE, "w") as f:
        json.dump({
            "max_id": state["max_id"],
            "count": state["count"],
            "page": state["page"],
            "progress_pct": state["count"] / TOTAL_FOLLOWERS * 100,
            "updated_at": datetime.now().isoformat(),
        }, f, indent=2)
    # 保存用户数据
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(state["users"], f, ensure_ascii=False, indent=2)


def get_headers(session):
    """获取请求头"""
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
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }


def fetch_one_page(session, headers, user_id, max_id):
    """获取一页粉丝数据，返回 (users_list, next_max_id, error)"""
    params = {"count": BATCH_SIZE}
    if max_id:
        params["max_id"] = max_id

    try:
        resp = session.get(
            f"https://www.instagram.com/api/v1/friendships/{user_id}/followers/",
            params=params,
            headers=headers,
            timeout=60,
        )
    except requests.exceptions.Timeout:
        return None, None, "timeout"
    except requests.exceptions.ConnectionError as e:
        return None, None, f"connection_error: {e}"
    except requests.exceptions.RequestException as e:
        return None, None, f"request_error: {e}"

    if resp.status_code == 429:
        return None, None, "rate_limited"
    if resp.status_code == 401:
        return None, None, "session_expired"
    if resp.status_code == 403:
        return None, None, f"forbidden: {resp.text[:100]}"
    if resp.status_code != 200:
        return None, None, f"http_{resp.status_code}: {resp.text[:150]}"

    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        return None, None, f"json_decode: {e}"

    users = data.get("users", [])
    next_max_id = data.get("next_max_id")

    return users, next_max_id, None


def parse_user(item):
    """提取用户数据"""
    return {
        "pk": item.get("pk"),
        "username": item.get("username"),
        "full_name": item.get("full_name", ""),
        "is_private": item.get("is_private", False),
        "is_verified": item.get("is_verified", False),
    }


def main(skip_check: bool = False, max_consec_429: int = MAX_CONSEC_429):
    loader = instaloader.Instaloader(quiet=True, download_pictures=False, download_videos=False)

    # 登录
    import browser_cookie3
    print(f"🔑 正在从 {BROWSER} 导入 cookies...")
    cookies = {}
    for cookie in browser_cookie3.edge(domain_name="instagram.com"):
        if "instagram.com" in cookie.domain:
            cookies[cookie.name] = cookie.value
    if not cookies:
        print("❌ 未找到 cookies")
        sys.exit(1)
    loader.context.update_cookies(cookies)
    if skip_check:
        # 限流时 test_login() 必定失败，直接信任 cookies
        login_name = cookies.get("ds_user") or "unknown"
        loader.context.username = login_name
        print(f"⚠️  已跳过登录验证（--skip-check），用户名标记为 {login_name}")
    else:
        login_name = loader.test_login()
        if not login_name:
            print("❌ 未检测到登录状态")
            print("   若正被限流（429），可加 --skip-check 跳过该校验")
            sys.exit(1)
        loader.context.username = login_name
        print(f"✅ 已登录为 {login_name}")

    profile = Profile.from_username(loader.context, USERNAME)
    user_id = profile.userid
    print(f"\n📊 目标: {profile.username} (ID: {user_id})")
    print(f"   粉丝总数: {TOTAL_FOLLOWERS:,}")
    print(f"{'='*60}\n")

    session = loader.context._session
    headers = get_headers(session)

    # 加载断点
    state = load_state()
    existing_usernames = {u["username"] for u in state["users"]}
    print(f"   去重后有效: {len(state['users'])} 个\n")

    max_id = state["max_id"]
    page = state["page"]
    consec_errors = 0
    no_data_count = 0
    last_save_count = state["count"]

    # ===== 主循环 =====
    while not stop_flag:
        page += 1
        users, next_max_id, error = fetch_one_page(session, headers, user_id, max_id)

        if error:
            consec_errors += 1
            if error == "rate_limited":
                if consec_errors > max_consec_429:
                    print(f"\n  ⛔ [{page}] 连续 {consec_errors} 次被限流，停止本轮"
                          f"（进度已保存，稍后重跑即可继续）")
                    break
                wait = RATE_LIMIT_WAIT * min(consec_errors, 5)
                print(f"\n  ⏳ [{page}] 频率限制! 等待 {wait}s (第{consec_errors}次)... ", end="", flush=True)
                for s in range(wait):
                    if stop_flag:
                        break
                    time.sleep(1)
                    if s % 15 == 14:
                        print("⬤", end="", flush=True)
                print(" 继续")
                continue
            elif error == "timeout":
                wait = 10 * consec_errors
                print(f"\n  ⏳ [{page}] 超时, 等待 {wait}s...")
                time.sleep(wait)
                continue
            elif "session_expired" in error:
                print(f"\n  ❌ [{page}] 会话过期! 请重新登录")
                break
            elif "forbidden" in error:
                print(f"\n  ❌ [{page}] 被拒绝访问: {error}")
                # 可能是IP被临时封, 等久一点
                wait = 120 * consec_errors
                print(f"     等待 {wait}s 后重试...")
                time.sleep(wait)
                continue
            else:
                print(f"\n  ⚠️ [{page}] 错误: {error}")
                if consec_errors >= 10:
                    print(f"     连续 {consec_errors} 次错误, 停止")
                    break
                time.sleep(5)
                continue

        # 成功
        consec_errors = 0

        if not users:
            no_data_count += 1
            if no_data_count >= 3:
                print(f"\n  📭 [{page}] 连续无数据, 可能已抓完")
                break
            # 可能只是空页, 继续
            if next_max_id:
                max_id = next_max_id
                continue
            else:
                print(f"\n  ✅ [{page}] 没有更多数据")
                break

        no_data_count = 0

        # 添加新用户（去重）
        new_count = 0
        for item in users:
            username = item.get("username")
            if username and username not in existing_usernames:
                state["users"].append(parse_user(item))
                existing_usernames.add(username)
                new_count += 1

        state["count"] = len(state["users"])
        state["max_id"] = next_max_id
        state["page"] = page

        # 进度显示
        pct = state["count"] / TOTAL_FOLLOWERS * 100
        bar_len = 30
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        eta_seconds = (TOTAL_FOLLOWERS - state["count"]) / BATCH_SIZE * NORMAL_DELAY
        eta_str = f"{eta_seconds/60:.0f}分" if eta_seconds < 3600 else f"{eta_seconds/3600:.1f}小时"

        print(
            f"\r  📦 [{page:>5}] {bar} {state['count']:>7,}/{TOTAL_FOLLOWERS:,} "
            f"({pct:>5.2f}%) +{new_count} | ETA ~{eta_str}   ",
            end="", flush=True
        )

        # 定期保存
        if state["count"] - last_save_count >= BATCH_SIZE * SAVE_INTERVAL:
            save_state(state)
            last_save_count = state["count"]
            print(f"\n  💾 已保存 ({state['count']:,} 个)")

        # 更新 cursor
        if not next_max_id:
            print(f"\n\n✅ 全部抓取完成! 共 {state['count']:,} 个粉丝")
            break
        max_id = next_max_id

        # 正常请求间隔
        time.sleep(NORMAL_DELAY)

    # ===== 最终保存 =====
    save_state(state)
    print(f"\n💾 最终数据已保存到 {DATA_FILE}")
    print(f"   状态文件: {STATE_FILE}")
    print(f"   共获取: {state['count']:,} / {TOTAL_FOLLOWERS:,} 个粉丝 ({state['count']/TOTAL_FOLLOWERS*100:.2f}%)")

    # 也保存一份只含用户名的列表方便查看
    name_file = f"{USERNAME}_follower_usernames.txt"
    with open(name_file, "w", encoding="utf-8") as f:
        for u in state["users"]:
            f.write(f"{u['username']}\n")
    print(f"   用户名列表: {name_file}")


def _parse_args():
    parser = argparse.ArgumentParser(description="极端稳健的 Instagram 粉丝采集器")
    parser.add_argument("--skip-check", action="store_true",
                        help="跳过 test_login() 登录校验（限流 429 时使用）")
    parser.add_argument("--max-consec-429", type=int, default=MAX_CONSEC_429,
                        help=f"连续 429 达到此次数就保存退出（默认 {MAX_CONSEC_429}）")
    return parser.parse_args()


if __name__ == "__main__":
    _args = _parse_args()
    main(skip_check=_args.skip_check, max_consec_429=_args.max_consec_429)
