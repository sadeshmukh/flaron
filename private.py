from utils import _env
from cache import get_cached_channel
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

            return data


# TODO: bulk? fuzzer?
