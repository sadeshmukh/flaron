from utils import _env
import aiohttp

PRIVATECHANNEL_BASE = _env("PRIVATECHANNEL_BASE")


async def cname_private(id: str) -> dict:
    url = f"{PRIVATECHANNEL_BASE}/channel/{id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as res:
            data = await res.json()
            if not data.get("success") and not data.get("ok"):
                return {"error": "channel doesn't exist"}

            return data


async def cid_by_name_private(name: str) -> dict:
    url = f"{PRIVATECHANNEL_BASE}/fakepostchannel?name={name}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as res:
            data = await res.json()
            if not data.get("success"):
                return {"error": "channel doesn't exist"}

            return data


# TODO: bulk? fuzzer?
