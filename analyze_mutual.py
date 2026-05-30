#!/usr/bin/env python3
"""获取相互关注用户的详细信息"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import instaloader
from instaloader import Profile

BROWSER = "edge"
USERNAMES = ["my_____29", "pikapikammmm", "____ylei", "milkbluebun", "panpan_susuh"]

def load_cookies(loader):
    import browser_cookie3
    cookies = {}
    for cookie in browser_cookie3.edge(domain_name="instagram.com"):
        if "instagram.com" in cookie.domain:
            cookies[cookie.name] = cookie.value
    loader.context.update_cookies(cookies)
    loader.context.username = loader.test_login()

loader = instaloader.Instaloader(quiet=True)
load_cookies(loader)

print(f"{'='*65}")
print(f"{'用户名':<22} {'全名':<20} {'粉丝':>10} {'关注':>8} {'帖子':>6} {'私密':>4} {'认证':>4}")
print(f"{'-'*65}")
for uname in USERNAMES:
    try:
        p = Profile.from_username(loader.context, uname)
        print(f"@{p.username:<20} {p.full_name:<20} {p.followers:>10,} {p.followees:>8,} {p.mediacount:>6} {'🔒' if p.is_private else '公开':>4} {'✅' if p.is_verified else '':>4}")
        # 获取最新帖子（如果有）
        if p.mediacount > 0:
            posts = list(p.get_posts())
            if posts:
                latest = posts[0]
                print(f"   └─ 最新帖子: {latest.date_utc} | 👍 {latest.likes:,} | 💬 {latest.comments:,}")
                if latest.caption:
                    caption = latest.caption[:80].replace('\n', ' ')
                    print(f"   └─ 描述: {caption}...")
    except Exception as e:
        print(f"@{uname:<20} {'获取失败':<20} | {e}")
