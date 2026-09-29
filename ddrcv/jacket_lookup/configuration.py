"""Measured working defaults for CPU splash recognition."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SplashConfiguration:
    catalog: str = 'event'
    event: str = 'dia_del_ritmo_26'
    style: str = 'single'
    splash_execution: str = 'threaded'
    difficulty_method: str = 'template'
    name_method: str = 'per-player'
    name_threads: int = 1
    high_qos: bool = True


WORKING_CONFIG = SplashConfiguration()
