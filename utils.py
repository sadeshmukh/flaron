import os


def _env(val: str, fallback: str = "") -> str:
    if not fallback:
        if os.getenv(val) is None:
            raise Exception(f"Env {val} not set")
    return os.getenv(val, fallback)
