from upstash_redis import Redis

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

redis = Redis.from_env()

_id_to_name: dict[str, str] = {}
_name_to_id: dict[str, str] = {}


def init_cache():
    cursor = 0
    while True:
        cursor, keys = redis.scan(cursor, match="channel:*", count=500)
        id_keys = [k for k in keys if not k.startswith("channel_name:")]
        if id_keys:
            values = redis.mget(*id_keys)
            for key, value in zip(id_keys, values):
                if value is not None:
                    cid = key[len("channel:") :]
                    _id_to_name[cid] = value
                    _name_to_id[value] = cid
        if cursor == 0:
            break


def cache_channel(id: str, name: str):
    _id_to_name[id] = name
    _name_to_id[name] = id
    pipe = redis.pipeline()
    pipe.set(f"channel:{id}", name)
    pipe.set(f"channel_name:{name}", id)
    pipe.exec()


def get_cached_channel(id: str) -> str | None:
    return _id_to_name.get(id)


def get_cached_channel_id(name: str) -> str | None:
    return _name_to_id.get(name)


def cache_channels(mapping: dict[str, str]):
    if not mapping:
        return
    for id, name in mapping.items():
        _id_to_name[id] = name
        _name_to_id[name] = id
    pipe = redis.pipeline()
    for id, name in mapping.items():
        pipe.set(f"channel:{id}", name)
        pipe.set(f"channel_name:{name}", id)
    pipe.exec()


def get_cached_channels(ids: list[str]) -> dict[str, str | None]:
    return {id: _id_to_name.get(id) for id in ids}


def get_all_cached_name_to_id() -> dict[str, str]:
    return dict(_name_to_id)


def invalidate_channel(id: str):
    name = _id_to_name.pop(id, None)
    if name:
        _name_to_id.pop(name, None)
    pipe = redis.pipeline()
    pipe.delete(f"channel:{id}")
    if name:
        pipe.delete(f"channel_name:{name}")
    pipe.exec()
