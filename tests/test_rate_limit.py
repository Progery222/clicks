"""Тесты rate limit."""

from app.services.rate_limit import allow_request


def test_rate_limit_blocks_after_threshold():
    ip = "203.0.113.99"
    for _ in range(5):
        assert allow_request(ip, limit_per_minute=5, bucket="test")
    assert not allow_request(ip, limit_per_minute=5, bucket="test")


def test_separate_buckets():
    assert allow_request("1.2.3.4", limit_per_minute=1, bucket="a")
    assert not allow_request("1.2.3.4", limit_per_minute=1, bucket="a")
    assert allow_request("1.2.3.4", limit_per_minute=1, bucket="b")
