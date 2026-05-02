from upstash_redis import Redis

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

redis = Redis.from_env()

def cache_channel(id: str, name: str):
    pipe = redis.pipeline()
    pipe.set(f"channel:{id}", name)
    pipe.set(f"channel_name:{name}", id)
    pipe.exec()


def get_cached_channel(id: str) -> str | None:
    return redis.get(f"channel:{id}")


def get_cached_channel_id(name: str) -> str | None:
    return redis.get(f"channel_name:{name}")


def cache_channels(mapping: dict[str, str]):
    if not mapping:
        return
    pipe = redis.pipeline()
    for id, name in mapping.items():
        pipe.set(f"channel:{id}", name)
        pipe.set(f"channel_name:{name}", id)
    pipe.exec()


def get_cached_channels(ids: list[str]) -> dict[str, str | None]:
    if not ids:
        return {}
    values = redis.mget(*[f"channel:{id}" for id in ids])
    return dict(zip(ids, values))


def invalidate_channel(id: str):
    name = redis.get(f"channel:{id}")
    pipe = redis.pipeline()
    pipe.delete(f"channel:{id}")
    if name:
        pipe.delete(f"channel_name:{name}")
    pipe.exec()
