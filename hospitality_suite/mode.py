"""Canonical lodging modes and compatibility with historical price snapshots."""

TIME_MODE = "Por tiempo"
LEGACY_TIME_MODE = "Motel"


def normalize_mode(value):
    return TIME_MODE if value == LEGACY_TIME_MODE else value


def is_time_mode(value):
    return value in (TIME_MODE, LEGACY_TIME_MODE)
