import os


def _env(val: str, fallback: str | None = None) -> str:
    if fallback is None:
        if os.getenv(val) is None:
            raise Exception(f"Env {val} not set")
    return os.getenv(val, fallback)  # type: ignore
