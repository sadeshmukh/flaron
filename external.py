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


async def trust_factor(user_id: str) -> dict:
    url = f"https://hackatime.hackclub.com/api/v1/users/{user_id}/trust_factor"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as res:
            data = await res.json()
            return data  # trust_level: verified, trust_value: 0/1/2 (blue/red/green/ (not yellow))


async def idv_verified(user_id: str) -> dict:
    url = f"https://auth.hackclub.com/api/external/check?slack_id={user_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as res:
            data = await res.json()
            # result: needs_submission, pending, verified_eligible, verified_but_over_18, rejected, not_found
            return data
