import json
import logging
import time

from upstash_redis import Redis
from upstash_redis.asyncio import Redis as AsyncRedis

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

redis = Redis.from_env()
async_redis = AsyncRedis.from_env()

CACHE_STREAM_KEY = "cache_updates"

CHANNEL_REC_PREFIX = "channel_rec:"
HISTORY_CAP = 20

# id -> {"history": [{"name": str, "ts": int}], "latest": str | None, "private": bool}
_channels: dict[str, dict] = {}
_name_to_id: dict[str, str] = {}  # latest names only; historical names never resolve

_failed_channels: set[str] = set()
_failed_channels_dirty: bool = False
FAILED_CHANNELS_KEY = "failed_channels"

_blacklisted_channels: set[str] = set()
BLACKLISTED_CHANNELS_KEY = "blacklisted_channels"

# pre-record-format keys: read once to seed channel_rec:*, never written back
LEGACY_ID_PREFIX = "channel:"
LEGACY_NAME_PREFIX = "channel_name:"
LEGACY_PRIVATE_IDS_KEY = "private_channel_ids"


def _apply_name(id: str, name: str, private: bool, ts: int) -> set[str]:
    """Make `name` the latest name of `id`, stealing it from any other record.

    Returns the ids whose records changed (callers persist/announce those)."""
    touched: set[str] = set()
    other_id = _name_to_id.get(name)
    if other_id is not None and other_id != id:
        _channels[other_id]["latest"] = None
        _name_to_id.pop(name, None)
        touched.add(other_id)
    rec = _channels.get(id)
    if rec is None:
        rec = {"history": [], "latest": None, "private": private}
        _channels[id] = rec
    if rec["latest"] != name or rec["private"] != private:
        touched.add(id)
    # append on regain too (latest != name), so the claim ts reflects when
    # the name was reacquired, not the original claim
    if rec["latest"] != name or not rec["history"] or rec["history"][-1]["name"] != name:
        rec["history"].append({"name": name, "ts": ts})
        del rec["history"][:-HISTORY_CAP]
        touched.add(id)
    if rec["latest"] and rec["latest"] != name and _name_to_id.get(rec["latest"]) == id:
        _name_to_id.pop(rec["latest"], None)
    rec["latest"] = name
    rec["private"] = private
    _name_to_id[name] = id
    return touched


def _apply_unlink(id: str) -> bool:
    rec = _channels.get(id)
    if rec is None or rec["latest"] is None:
        return False
    if _name_to_id.get(rec["latest"]) == id:
        _name_to_id.pop(rec["latest"], None)
    rec["latest"] = None
    return True


def _persist(ids) -> None:
    ids = list(ids)
    for i in range(0, len(ids), 500):
        pipe = redis.pipeline()
        for cid in ids[i : i + 500]:
            pipe.set(
                f"{CHANNEL_REC_PREFIX}{cid}",
                json.dumps(_channels[cid], separators=(",", ":")),
            )
        pipe.exec()


def _emit_set(id: str, name: str, private: bool, ts: int) -> None:
    redis.xadd(
        CACHE_STREAM_KEY,
        "*",
        {"op": "s", "i": id, "n": name, "p": "1" if private else "0", "t": str(ts)},
        maxlen=1000,
        approximate_trim=True,
    )


def _display_name(rec: dict) -> str | None:
    if rec["latest"]:
        return rec["latest"]
    if rec["history"]:
        return rec["history"][-1]["name"]
    return None


def _claim_ts(rec: dict) -> int:
    return rec["history"][-1]["ts"] if rec["history"] else 0


def _seed_from_legacy():
    legacy: dict[str, str] = {}
    cursor = 0
    while True:
        cursor, keys = redis.scan(cursor, match=f"{LEGACY_ID_PREFIX}*", count=500)
        if keys:
            values = redis.mget(*keys)
            for key, name in zip(keys, values):
                if name is not None:
                    legacy[key[len(LEGACY_ID_PREFIX) :]] = name
        if cursor == 0:
            break
    if not legacy:
        return
    private_ids = set(redis.smembers(LEGACY_PRIVATE_IDS_KEY) or [])
    ts = int(time.time())
    seeded = set()
    for id, name in legacy.items():
        if id in _channels:
            continue
        _channels[id] = {
            "history": [{"name": name, "ts": ts}],
            "latest": name,
            "private": id in private_ids,
        }
        seeded.add(id)
    if seeded:
        logging.info(f"seeded {len(seeded)} channel records from legacy cache")
        _persist(seeded)


def init_cache():
    cursor = 0
    while True:
        cursor, keys = redis.scan(cursor, match=f"{CHANNEL_REC_PREFIX}*", count=500)
        if keys:
            values = redis.mget(*keys)
            for key, raw in zip(keys, values):
                if raw is None:
                    continue
                try:
                    rec = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    logging.warning(f"unreadable channel record at {key}")
                    continue
                _channels[key[len(CHANNEL_REC_PREFIX) :]] = {
                    "history": rec.get("history", []),
                    "latest": rec.get("latest"),
                    "private": rec.get("private", False),
                }
        if cursor == 0:
            break

    _seed_from_legacy()

    # build the latest-name index; if two records claim a name, the newer claim wins
    demoted = set()
    for id, rec in _channels.items():
        name = rec["latest"]
        if not name:
            continue
        other_id = _name_to_id.get(name)
        if other_id is None:
            _name_to_id[name] = id
        elif _claim_ts(rec) >= _claim_ts(_channels[other_id]):
            _channels[other_id]["latest"] = None
            demoted.add(other_id)
            _name_to_id[name] = id
        else:
            rec["latest"] = None
            demoted.add(id)
    _persist(demoted)

    failed = redis.smembers(FAILED_CHANNELS_KEY)
    if failed:
        _failed_channels.update(failed)

    blacklisted = redis.smembers(BLACKLISTED_CHANNELS_KEY)
    if blacklisted:
        _blacklisted_channels.update(blacklisted)


def cache_channel(id: str, name: str, private: bool = False):
    ts = int(time.time())
    touched = _apply_name(id, name, private, ts)
    if not touched:
        return
    _persist(touched)
    _emit_set(id, name, private, ts)


def cache_channels(mapping: dict[str, dict]):
    # mapping: {id: {"name": str, "private": bool}}
    logging.info(f"caching {len(mapping)} channels")
    if not mapping:
        return
    ts = int(time.time())
    touched: set[str] = set()
    changed: list[tuple[str, str, bool]] = []
    for id, data in mapping.items():
        name = data["name"]
        private = data.get("private", False)
        applied = _apply_name(id, name, private, ts)
        if applied:
            changed.append((id, name, private))
        touched |= applied
    if not touched:
        return
    _persist(touched)
    for id, name, private in changed:
        _emit_set(id, name, private, ts)


def get_cached_channel(id: str) -> str | None:
    rec = _channels.get(id)
    return _display_name(rec) if rec else None


def get_cached_channel_id(name: str) -> dict | None:
    id = _name_to_id.get(name)
    if id is None:
        return None
    return {"id": id, "private": _channels[id]["private"]}


def get_cached_channels(ids: list[str]) -> dict[str, str | None]:
    return {id: get_cached_channel(id) for id in ids}


def search_cached_channels(query: str) -> list[dict]:
    q = query.lower()
    return [
        {"name": name, "id": id, "private": _channels[id]["private"]}
        for name, id in _name_to_id.items()
        if q in name.lower()
    ]


def get_all_records() -> dict[str, dict]:
    return {
        id: {
            "history": list(rec["history"]),
            "latest": rec["latest"],
            "private": rec["private"],
        }
        for id, rec in _channels.items()
    }


def get_stale_records() -> list[dict]:
    return [
        {
            "id": id,
            "last_known_name": rec["history"][-1]["name"] if rec["history"] else None,
            "history": list(rec["history"]),
        }
        for id, rec in _channels.items()
        if rec["latest"] is None
    ]


def unlink_channel(id: str):
    if not _apply_unlink(id):
        return
    _persist({id})
    redis.xadd(
        CACHE_STREAM_KEY,
        "*",
        {"op": "u", "i": id},
        maxlen=1000,
        approximate_trim=True,
    )


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


def blacklist_channel(id: str):
    _blacklisted_channels.add(id)
    redis.sadd(BLACKLISTED_CHANNELS_KEY, id)


def unblacklist_channel(id: str):
    _blacklisted_channels.discard(id)
    redis.srem(BLACKLISTED_CHANNELS_KEY, id)


def is_channel_blacklisted(id: str) -> bool:
    return id in _blacklisted_channels


def get_blacklisted_channels() -> set[str]:
    return set(_blacklisted_channels)


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


def get_stream_last_id() -> str:
    entries = redis.xrevrange(CACHE_STREAM_KEY, count=1)
    if entries:
        return entries[0][0]
    return "0-0"


def _apply_stream_event(fields: dict):
    op = fields.get("op")
    if op == "s":
        try:
            ts = int(fields.get("t") or time.time())
        except ValueError:
            ts = int(time.time())
        _apply_name(fields["i"], fields["n"], fields.get("p") == "1", ts)
    elif op in ("u", "d"):
        # "d" is the pre-record-format delete op; treat it as an unlink
        _apply_unlink(fields["i"])


async def cache_update_loop(poll_interval: float = 30.0):
    import asyncio

    last_id = get_stream_last_id()
    while True:
        await asyncio.sleep(poll_interval)
        try:
            results = await async_redis.xread(
                streams={CACHE_STREAM_KEY: last_id}, count=100
            )
            if not results:
                continue
            for _stream, entries in results:
                for entry_id, flat_fields in entries:
                    last_id = entry_id
                    _apply_stream_event(dict(zip(flat_fields[::2], flat_fields[1::2])))
        except Exception as e:
            logging.warning(f"cache stream poll error: {e}")


def purge_channel_cache():
    _channels.clear()
    _name_to_id.clear()
    for pattern in (
        f"{CHANNEL_REC_PREFIX}*",
        f"{LEGACY_ID_PREFIX}*",
        f"{LEGACY_NAME_PREFIX}*",
    ):
        cursor = 0
        while True:
            cursor, keys = redis.scan(cursor, match=pattern, count=500)
            if keys:
                pipe = redis.pipeline()
                for key in keys:
                    pipe.delete(key)
                pipe.exec()
            if cursor == 0:
                break
    redis.delete(LEGACY_PRIVATE_IDS_KEY)
