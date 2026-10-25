"""Shared random source. Mirrors com.mechalikh.pureedgesim.distribution.Randomness."""
from __future__ import annotations

import random
import threading

_MASK = (1 << 64) - 1


def _mix(seed: int, salt: int) -> int:
    value = (seed + 0x9E3779B97F4A7C15 + salt * 0x1000003) & _MASK
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK
    return value ^ (value >> 31)


class Randomness:
    """One reproducible stream per thread, derived from a single seed."""

    _seed: int | None = None
    _salt: int = 0
    _local = threading.local()
    _fallback = random.Random()

    @classmethod
    def set_seed(cls, seed: int | None) -> None:
        cls._seed = seed
        cls._local = threading.local()

    @classmethod
    def get_seed(cls) -> int | None:
        return cls._seed

    @classmethod
    def begin_scenario(cls, salt: int) -> None:
        cls._salt = int(salt)
        cls._local = threading.local()

    @classmethod
    def get_random(cls) -> random.Random:
        if cls._seed is None:
            return cls._fallback
        stream = getattr(cls._local, "stream", None)
        if stream is None:
            stream = random.Random(_mix(cls._seed, cls._salt))
            cls._local.stream = stream
        return stream

    @classmethod
    def reset(cls) -> None:
        cls._seed = None
        cls._salt = 0
        cls._local = threading.local()
        cls._fallback = random.Random()
