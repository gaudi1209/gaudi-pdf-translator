import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.translation_cache import TranslationCache


def test_cache_miss():
    """未命中缓存返回 None"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TranslationCache(tmpdir)
        result = cache.get("hello world", "translategemma:27b")
        assert result is None
        cache.close()


def test_cache_hit():
    """写入后可命中"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TranslationCache(tmpdir)
        cache.put("hello world", "你好世界", "translategemma:27b")
        result = cache.get("hello world", "translategemma:27b")
        assert result == "你好世界"
        cache.close()


def test_cache_different_models():
    """不同模型不互相干扰"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TranslationCache(tmpdir)
        cache.put("hello", "你好", "model_a")
        cache.put("hello", "안녕", "model_b")
        assert cache.get("hello", "model_a") == "你好"
        assert cache.get("hello", "model_b") == "안녕"
        cache.close()


def test_cache_persistence():
    """缓存持久化到磁盘"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache1 = TranslationCache(tmpdir)
        cache1.put("test", "测试", "model")
        cache1.close()

        cache2 = TranslationCache(tmpdir)
        assert cache2.get("test", "model") == "测试"
        cache2.close()


def test_cache_stats():
    """缓存统计"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TranslationCache(tmpdir)
        cache.put("a", "甲", "m")
        cache.put("b", "乙", "m")
        stats = cache.stats()
        assert stats["total_entries"] == 2
        cache.close()
