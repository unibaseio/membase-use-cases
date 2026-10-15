"""Per-plan limits: (requests per second, burst)."""

from .bucket import TokenBucket

PLANS = {"free": (5, 5), "team": (50, 100), "enterprise": (500, 1000)}


def bucket_for(plan: str, clock=None) -> TokenBucket:
    rate, burst = PLANS[plan]
    return TokenBucket(rate, burst, **({"clock": clock} if clock else {}))
