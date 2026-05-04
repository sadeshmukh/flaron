from upstash_redis import Redis

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

redis = Redis.from_env()

_id_to_name: dict[str, str] = {}
_name_to_data: dict[str, dict] = {}  # name -> {"id": str, "private": bool}

_failed_channels: set[str] = set()
_failed_channels_dirty: bool = False
FAILED_CHANNELS_KEY = "failed_channels"
PRIVATE_CHANNEL_IDS_KEY = "private_channel_ids"


def init_cache():
    cursor = 0
    while True:
        cursor, keys = redis.scan(cursor, match="channel:*", count=500)
        id_keys = [k for k in keys if not k.startswith("channel_name:")]
        if id_keys:
            values = redis.mget(*id_keys)
            for key, value in zip(id_keys, values):
                if value is not None:
                    cid = key[len("channel:"):]
                    _id_to_name[cid] = value
        if cursor == 0:
            break

    private_ids = set(redis.smembers(PRIVATE_CHANNEL_IDS_KEY) or [])
    for cid, name in _id_to_name.items():
        _name_to_data[name] = {"id": cid, "private": cid in private_ids}

    failed = redis.smembers(FAILED_CHANNELS_KEY)
    if failed:
        _failed_channels.update(failed)


def cache_channel(id: str, name: str, private: bool = False):
    _id_to_name[id] = name
    _name_to_data[name] = {"id": id, "private": private}
    pipe = redis.pipeline()
    pipe.set(f"channel:{id}", name)
    pipe.set(f"channel_name:{name}", id)
    if private:
        pipe.sadd(PRIVATE_CHANNEL_IDS_KEY, id)
    else:
        pipe.srem(PRIVATE_CHANNEL_IDS_KEY, id)
    pipe.exec()


def get_cached_channel(id: str) -> str | None:
    return _id_to_name.get(id)


def get_cached_channel_id(name: str) -> dict | None:
    return _name_to_data.get(name)


def cache_channels(mapping: dict[str, dict]):
    # mapping: {id: {"name": str, "private": bool}}
    if not mapping:
        return
    private_ids = []
    public_ids = []
    pipe = redis.pipeline()
    for id, data in mapping.items():
        name = data["name"]
        private = data.get("private", False)
        _id_to_name[id] = name
        _name_to_data[name] = {"id": id, "private": private}
        pipe.set(f"channel:{id}", name)
        pipe.set(f"channel_name:{name}", id)
        if private:
            private_ids.append(id)
        else:
            public_ids.append(id)
    if private_ids:
        pipe.sadd(PRIVATE_CHANNEL_IDS_KEY, *private_ids)
    if public_ids:
        pipe.srem(PRIVATE_CHANNEL_IDS_KEY, *public_ids)
    pipe.exec()


def get_cached_channels(ids: list[str]) -> dict[str, str | None]:
    return {id: _id_to_name.get(id) for id in ids}


def search_cached_channels(query: str) -> dict[str, str]:
    q = query.lower()
    cursor = 0
    results = {}
    while True:
        cursor, keys = redis.scan(cursor, match=f"channel_name:*{q}*", count=500)
        for key in keys:
            name = key[len("channel_name:"):]
            cid = redis.get(key)
            if cid:
                results[name] = cid
        if cursor == 0:
            break
    return results


def get_all_cached_name_to_id() -> dict[str, dict]:
    return dict(_name_to_data)


def mark_channel_failed(id: str):
    global _failed_channels_dirty
    if id not in _failed_channels:
        _failed_channels.add(id)
        _failed_channels_dirty = True


def unmark_channel_failed(id: str):
    if id in _failed_channels:
        _failed_channels.discard(id)
        redis.srem(FAILED_CHANNELS_KEY, id)


def is_channel_failed(id: str) -> bool:
    return id in _failed_channels


def sync_failed_channels():
    global _failed_channels_dirty
    if not _failed_channels_dirty:
        return
    if _failed_channels:
        redis.sadd(FAILED_CHANNELS_KEY, *_failed_channels)
    _failed_channels_dirty = False


async def failed_channels_sync_loop(interval: int = 60):
    import asyncio

    while True:
        await asyncio.sleep(interval)
        sync_failed_channels()


def invalidate_channel(id: str):
    name = _id_to_name.pop(id, None)
    if name:
        _name_to_data.pop(name, None)
    pipe = redis.pipeline()
    pipe.delete(f"channel:{id}")
    if name:
        pipe.delete(f"channel_name:{name}")
    pipe.srem(PRIVATE_CHANNEL_IDS_KEY, id)
    pipe.exec()


def purge_channel_cache():
    _id_to_name.clear()
    _name_to_data.clear()
    cursor = 0
    pipe = redis.pipeline()
    while True:
        cursor, keys = redis.scan(cursor, match="channel:*", count=500)
        for key in keys:
            pipe.delete(key)
        if cursor == 0:
            break
    pipe.delete(PRIVATE_CHANNEL_IDS_KEY)
    pipe.exec()
