#!/usr/bin/env python3
"""按端点分类的滑动窗口限速器。

本模块把手写 ``requests.Session.get()`` 的请求纳入与上游 instaloader
``RateController`` 一致的限速规则，避免自定义脚本绕过限速而被 Instagram 限流。

上游参数（``instaloader/instaloadercontext.py::RateController``）：

======================  ==========================  ==================
端点类型                上限                        滑动窗口
======================  ==========================  ==================
``other``               75 次                       660 秒（11 分钟）
（www 的 REST 端点，                                 ≈ 8.8 秒/次
如 ``friendships/*``）
``graphql`` / doc_id    200 次                      660 秒
``iphone``              199 次                      1800 秒（30 分钟）
所有 graphql 累计        275 次                      600 秒
======================  ==========================  ==================

用法::

    from rate_limiter import get_limiter

    limiter = get_limiter()          # 默认 upstream 档位
    limiter.acquire(url)             # 请求前调用：必要时等待并登记
    resp = session.get(url, ...)
    if resp.status_code == 429:
        limiter.penalize(url)        # 429 后进入冷却，避免继续踩限流
"""
import os
import threading
import time
from typing import Dict, List, Optional

# ---- 上游 instaloader RateController 的参数 ----
PER_TYPE_WINDOW = 660.0      # 'other' / 'graphql' 的滑动窗口（秒）
IPHONE_WINDOW = 1800.0       # iphone API 的滑动窗口（秒）
GQL_ACC_WINDOW = 600.0       # 所有 graphql 累计窗口（秒）
GQL_ACC_MAX_COUNT = 275      # 所有 graphql 累计上限

# 档位：直接对应上游的 count_per_sliding_window() 返回值
PROFILES: Dict[str, Optional[Dict[str, int]]] = {
    # 严格遵循上游参数（推荐）
    "upstream": {"other": 75, "graphql": 200, "iphone": 199},
    # 更保守：约为上游的 70%，适合已出现 429 时使用
    "conservative": {"other": 52, "graphql": 140, "iphone": 139},
    # 关闭主动限速（仅保留调用方自己的固定延迟，自担风险）
    "off": None,
}

DEFAULT_PROFILE = os.getenv("IG_RATE_PROFILE", "upstream")

# 429 后的冷却基准（秒），每次连续 429 递增，上限 30 分钟
COOLDOWN_BASE = 60.0
COOLDOWN_MAX = 1800.0


def classify_url(url_or_key: str) -> str:
    """把 URL 归入上游的四类之一（``iphone`` / ``graphql`` / ``other``）。"""
    if "://" not in url_or_key:
        return url_or_key
    if "i.instagram.com" in url_or_key:
        return "iphone"
    if "graphql/query" in url_or_key:
        return "graphql"
    return "other"


class SlidingWindowRateLimiter:
    """按端点类型分别计数的滑动窗口限速器（线程安全）。"""

    def __init__(self, profile: str = DEFAULT_PROFILE,
                 min_interval: float = 0.0,
                 verbose: bool = True):
        limits = PROFILES.get(profile, PROFILES["upstream"])
        self.profile = profile if limits is not None else "off"
        self.enabled = limits is not None
        self._limits = dict(limits) if limits else {}
        self._min_interval = max(0.0, min_interval)
        self._verbose = verbose
        self._timestamps: Dict[str, List[float]] = {}
        self._last_request = 0.0
        self._cooldown_until = 0.0
        self._consecutive_429 = 0
        self._lock = threading.RLock()

    # ---------- 内部 ----------
    def _window_for(self, key: str) -> float:
        return IPHONE_WINDOW if key == "iphone" else PER_TYPE_WINDOW

    def _prune(self, key: str, now: float) -> None:
        window = self._window_for(key)
        self._timestamps[key] = [t for t in self._timestamps.get(key, []) if t > now - window]

    def _graphql_accumulated_wait(self, now: float) -> float:
        """所有 graphql 类请求的累计限制（上游 275 次 / 600 秒）。"""
        times: List[float] = []
        for key, stamps in self._timestamps.items():
            if key not in ("iphone", "other"):
                times.extend(t for t in stamps if t > now - GQL_ACC_WINDOW)
        if len(times) < GQL_ACC_MAX_COUNT:
            return 0.0
        return (min(times) + GQL_ACC_WINDOW) - now

    def wait_time(self, url_or_key: str) -> float:
        """返回还需等待的秒数（0 表示可以立即发请求）。"""
        if not self.enabled:
            return 0.0
        key = classify_url(url_or_key)
        now = time.monotonic()
        with self._lock:
            wait = 0.0
            # 429 冷却期
            if self._cooldown_until > now:
                wait = self._cooldown_until - now
            self._prune(key, now)
            limit = self._limits.get(key, self._limits.get("other", 75))
            stamps = self._timestamps[key]
            if len(stamps) >= limit:
                wait = max(wait, (min(stamps) + self._window_for(key)) - now)
            if key != "iphone":
                wait = max(wait, self._graphql_accumulated_wait(now))
            if self._min_interval > 0:
                wait = max(wait, self._last_request + self._min_interval - now)
            return max(0.0, wait)

    # ---------- 对外 ----------
    def acquire(self, url_or_key: str, sleep: bool = True) -> float:
        """请求前调用：必要时等待，然后登记本次请求。返回实际等待秒数。"""
        if not self.enabled:
            return 0.0
        key = classify_url(url_or_key)
        waited = 0.0
        while True:
            wait = self.wait_time(url_or_key)
            if wait <= 0:
                break
            if not sleep:
                return wait
            if self._verbose and wait > 5:
                print(f"   ⏳ 限速：{key} 类请求需等待 {wait:.0f}s", flush=True)
            # 分片休眠，便于及时响应信号
            time.sleep(min(wait, 10.0))
            waited += min(wait, 10.0)
        with self._lock:
            self._timestamps.setdefault(key, []).append(time.monotonic())
            self._last_request = time.monotonic()
        return waited

    def penalize(self, url_or_key: str) -> float:
        """收到 429 后调用：进入冷却并降低后续速率。返回冷却秒数。"""
        key = classify_url(url_or_key)
        with self._lock:
            self._consecutive_429 += 1
            cooldown = min(COOLDOWN_BASE * self._consecutive_429, COOLDOWN_MAX)
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + cooldown)
        if self._verbose:
            print(f"   ⛔ {key} 类端点被限流（连续第 {self._consecutive_429} 次），"
                  f"冷却 {cooldown:.0f}s", flush=True)
        return cooldown

    def reward(self) -> None:
        """请求成功后调用：逐步消除 429 惩罚。"""
        with self._lock:
            if self._consecutive_429:
                self._consecutive_429 = max(0, self._consecutive_429 - 1)
            if self._consecutive_429 == 0:
                self._cooldown_until = 0.0

    def steady_interval(self, url_or_key: str) -> float:
        """返回该类请求的稳态最小间隔（秒/次）。

        用于估算 ETA：滑动窗口允许突发（窗口内未超上限时不等待），
        但长期平均速率不会超过 ``窗口 / 上限``。

        注意需与 ``--min-interval`` 取大 —— 否则传了 ``--min-interval``
        时 ETA 会被严重低估（实际按 min_interval 走，ETA 却按窗口算）。
        """
        if not self.enabled:
            return self._min_interval
        key = classify_url(url_or_key)
        limit = self._limits.get(key, self._limits.get("other", 75)) or 1
        return max(self._min_interval, self._window_for(key) / limit)

    def describe(self) -> str:
        if not self.enabled:
            base = "主动限速已关闭（仅靠固定延迟）"
        else:
            parts = ", ".join(f"{k}={v}/{int(self._window_for(k))}s"
                              for k, v in sorted(self._limits.items()))
            base = f"限速档位 {self.profile}（{parts}）"
        if self._min_interval > 0:
            base += f" + 最小间隔 {self._min_interval:.0f}s"
        return base


_limiter: Optional[SlidingWindowRateLimiter] = None
_limiter_lock = threading.Lock()


def get_limiter(profile: Optional[str] = None,
                min_interval: Optional[float] = None,
                verbose: bool = True) -> SlidingWindowRateLimiter:
    """获取全局限速器（首次调用时创建）。"""
    global _limiter
    with _limiter_lock:
        if _limiter is None:
            _limiter = SlidingWindowRateLimiter(
                profile=profile or DEFAULT_PROFILE,
                min_interval=min_interval or 0.0,
                verbose=verbose,
            )
    return _limiter


def reset_limiter() -> None:
    """重置全局限速器（测试或切换档位时使用）。"""
    global _limiter
    with _limiter_lock:
        _limiter = None


def add_profile_args(parser) -> None:
    """为脚本的 argparse 添加限速相关参数。"""
    group = parser.add_argument_group("限速（反爬）设置")
    group.add_argument("--rate-profile", choices=sorted(PROFILES), default=DEFAULT_PROFILE,
                       help="限速档位（默认 upstream，即遵循 instaloader 上游参数）")
    group.add_argument("--min-interval", type=float, default=None,
                       help="同一进程内两次请求的最小间隔秒数（默认 0）")
