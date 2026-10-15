import unittest

from ratelimit.plans import bucket_for


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class TokenBucketTest(unittest.TestCase):
    def test_burst_then_limit(self):
        clock = FakeClock()
        bucket = bucket_for("free", clock)
        allowed = sum(bucket.allow() for _ in range(50))
        self.assertEqual(allowed, 5)

    def test_refills_at_rate(self):
        clock = FakeClock()
        bucket = bucket_for("free", clock)
        for _ in range(5):
            bucket.allow()
        clock.now += 1.0
        allowed = sum(bucket.allow() for _ in range(50))
        self.assertEqual(allowed, 5)

    def test_long_uptime_still_limits(self):
        clock = FakeClock()
        bucket = bucket_for("free", clock)
        clock.now += 120.0  # the process has been up for two minutes
        allowed = sum(bucket.allow() for _ in range(50))
        self.assertEqual(allowed, 5)


if __name__ == "__main__":
    unittest.main()
