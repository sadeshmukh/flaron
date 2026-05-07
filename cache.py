import logging

from upstash_redis import Redis
from upstash_redis.asyncio import Redis as AsyncRedis

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

redis = Redis.from_env()
async_redis = AsyncRedis.from_env()

CACHE_STREAM_KEY = "cache_updates"

_id_to_name: dict[str, str] = {}
_name_to_data: dict[str, dict] = {}  # name -> {"id": str, "private": bool}

_failed_channels: set[str] = set()
_failed_channels_dirty: bool = False
FAILED_CHANNELS_KEY = "failed_channels"
PRIVATE_CHANNEL_IDS_KEY = "private_channel_ids"


def init_cache():
    cursor = 0
    while True:
        cursor, keys = redis.scan(cursor, match="channel_name:*", count=500)
        if keys:
            values = redis.mget(*keys)
            for key, cid in zip(keys, values):
                if cid is not None:
                    name = key[len("channel_name:") :]
                    _id_to_name[cid] = name
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
    redis.xadd(CACHE_STREAM_KEY, "*", {"op": "s", "i": id, "n": name, "p": "1" if private else "0"}, maxlen=1000, approximate_trim=True)


def get_cached_channel(id: str) -> str | None:
    return _id_to_name.get(id)


def get_cached_channel_id(name: str) -> dict | None:
    return _name_to_data.get(name)


def cache_channels(mapping: dict[str, dict]):
    # mapping: {id: {"name": str, "private": bool}}
    logging.info(f"caching {len(mapping)} channels")
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
    for id, data in mapping.items():
        redis.xadd(CACHE_STREAM_KEY, "*", {"op": "s", "i": id, "n": data["name"], "p": "1" if data.get("private") else "0"}, maxlen=1000, approximate_trim=True)


def get_cached_channels(ids: list[str]) -> dict[str, str | None]:
    return {id: _id_to_name.get(id) for id in ids}


def search_cached_channels(query: str) -> list[dict]:
    q = query.lower()
    return [
        {"name": name, "id": data["id"], "private": data.get("private", False)}
        for name, data in _name_to_data.items()
        if q in name.lower()
    ]


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
    redis.xadd(CACHE_STREAM_KEY, "*", {"op": "d", "i": id}, maxlen=1000, approximate_trim=True)


def get_stream_last_id() -> str:
    entries = redis.xrevrange(CACHE_STREAM_KEY, count=1)
    if entries:
        return entries[0][0]
    return "0-0"


def _apply_stream_event(fields: dict):
    op = fields.get("op")
    if op == "s":
        eid, name, private = fields["i"], fields["n"], fields.get("p") == "1"
        _id_to_name[eid] = name
        _name_to_data[name] = {"id": eid, "private": private}
    elif op == "d":
        eid = fields["i"]
        old_name = _id_to_name.pop(eid, None)
        if old_name:
            _name_to_data.pop(old_name, None)


async def cache_update_loop(poll_interval: float = 2.0):
    import asyncio

    last_id = get_stream_last_id()
    while True:
        await asyncio.sleep(poll_interval)
        try:
            results = await async_redis.xread(streams={CACHE_STREAM_KEY: last_id}, count=100)
            if not results:
                continue
            for _stream, entries in results:
                for entry_id, fields in entries:
                    last_id = entry_id
                    _apply_stream_event(fields)
        except Exception as e:
            logging.warning(f"cache stream poll error: {e}")


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
