import time
import threading

class TokenBucket:
    """
    TokenBucket controls the rate of requests. It ensures that only a certain number
    of requests can be made per second, based on the provided rate.
    """
    def __init__(self, rate, capacity):
        """
        Initialize the TokenBucket.

        :param rate: The number of tokens (requests) that can be added per second.
        :param capacity: The maximum number of tokens in the bucket.
        """
        self.rate = rate  # Tokens per second
        self.capacity = capacity  # Maximum number of tokens
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def consume(self, tokens=1):
        """
        Attempt to consume a token from the bucket. If a token is available, it is consumed.
        If no tokens are available, the function waits until a token becomes available.

        :param tokens: The number of tokens to consume (default is 1).
        :return: True if a token was consumed, False otherwise.
        """
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens += elapsed * self.rate
            if self.tokens > self.capacity:
                self.tokens = self.capacity
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
