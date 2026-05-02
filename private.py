from utils import _env
from cache import cache_channel, get_cached_channel, get_cached_channel_id
import aiohttp

PRIVATECHANNEL_BASE = _env("PRIVATECHANNEL_BASE")


async def cname_private(id: str) -> dict:
    if cached := get_cached_channel(id):
        return {"name": cached}

    url = f"{PRIVATECHANNEL_BASE}/channel/{id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as res:
            data = await res.json()
            if not data.get("success") and not data.get("ok"):
                return {"error": "channel doesn't exist"}

            if name := data.get("name"):
                cache_channel(id, name)
            return data


async def cid_by_name_private(name: str) -> dict:
    if cached := get_cached_channel_id(name):
        return {"id": cached}

    url = f"{PRIVATECHANNEL_BASE}/fakepostchannel?name={name}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as res:
            data = await res.json()
            if not data.get("success"):
                return {"error": "channel doesn't exist"}

            if id := data.get("id"):
                cache_channel(id, name)
            return data


# TODO: bulk? fuzzer?
