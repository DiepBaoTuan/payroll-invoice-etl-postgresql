import time
from datetime import datetime, UTC

IDLE_SECONDS = 0.0


def now_utc():
    return datetime.now(UTC)


def start_timer():
    return time.perf_counter()


def elapsed_seconds(start_time):
    return time.perf_counter() - start_time


def track_input(prompt):
    global IDLE_SECONDS

    idle_start = time.perf_counter()
    value = input(prompt)
    IDLE_SECONDS += time.perf_counter() - idle_start

    return value


def get_idle_seconds():
    return IDLE_SECONDS