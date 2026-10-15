"""A token bucket: `rate` tokens per second, holding at most `capacity`."""

import time


class TokenBucket:
    def __init__(self, rate: float, capacity: float, clock=time.monotonic):
        self.rate = rate
        self.capacity = capacity
        self.clock = clock
        self.tokens = capacity
        self.created_at = clock()
        self.updated_at = self.created_at

    def _refill(self) -> None:
        now = self.clock()
        elapsed = now - self.created_at
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.updated_at = now

    def allow(self, cost: float = 1.0) -> bool:
        """Take `cost` tokens if there are enough; True when the request may go ahead."""
        self._refill()
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False
