import logging

from utils import _env
import aiohttp


async def get_email(uid: str):  # no API access for now
    async with aiohttp.ClientSession(
        headers={"Authorization": f"Bearer {_env('INFO_XOXB')}"}
    ) as session:
        async with session.get(
            "https://slack.com/api/users.info", params={"user": uid}
        ) as res:
            data = await res.json()
            if not data.get("ok"):
                logging.error(data)
                return {"error": data.get("error", "unknown")}
            if not (e := data.get("user", {}).get("profile", {}).get("email", "")):
                logging.error(data)
                return {"error": data.get("error", "email not found?")}
            return {"data": e}
