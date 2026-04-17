import json

import aiohttp
import logging
from utils import _env
from urllib.parse import quote, urlencode

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()


logger = logging.getLogger(__name__)

XOXC = _env("XOXC")
XOXD = _env("XOXD")
BASE = "https://hackclub.enterprise.slack.com/api/"

# region primitives


async def req(
    path: str, form: dict[str, str] = {}, params: dict[str, str] = {}
) -> dict:
    headers = {"Cookie": f"d={quote(XOXD)}", "Accept": "*/*"}
    params.update({"slack_route": "E09V59WQY1E:E09V59WQY1E"})
    url = f"{BASE}{path}?{urlencode(params)}"
    logging.info(url)
    form.update({"token": quote(XOXC)})
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(url, data=form) as res:
            data = await res.json()
            if not data.get("ok"):
                logging.info(
                    f"error in {path}: {data.get('error', 'this should never be seen')}"
                )
                return {"error": data.get("error")}

            return data


async def edge(path: str, jsondata: dict = {}, params: dict[str, str] = {}) -> dict:
    headers = {
        "Accept": "*/*",
        "Cookie": f"d={quote(XOXD)}; d-s={_env('DS')}; ic={_env('DS')}",
    }
    url = f"https://edgeapi.slack.com/cache/E09V59WQY1E/{path}"

    jsondata.update({"as_admin": True, "token": XOXC, "enterprise_token": XOXC})
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(
            url, data=json.dumps(jsondata, separators=(",", ":"))
        ) as res:
            data = await res.json()
            print(data)
            if not data.get("ok"):
                logging.info(
                    f"error in {path}: {data.get('error', 'this should never be seen')}"
                )
                return {"error": data.get("error")}

            return data


# endregion primitives


async def channel_managers(channel_id: str) -> dict:
    data = await req(
        "admin.roles.entity.listAssignments", form={"entity_id": channel_id}
    )
    if err := data.get("error", ""):
        pretty = (
            "private"
            if err == "no_perms"
            else "nonexistent" if err == "invalid_entity_id" else "unknown"
        )
        if pretty == "unknown":
            logger.error(f"what in the world is this error in {channel_id}: {err}")
        return {"error": pretty}
    try:
        return {"data": data.get("role_assignments", [])[0].get("users", [])}
    except Exception:
        logger.debug(f"Failed to get managers for {channel_id}")
        return {"data": []}


async def channel_counts(channel_id: str) -> dict:
    data = await edge("users/counts", jsondata={"channel": channel_id})
    # lots of extraneous, just show: total, bots
    if err := data.get("error", ""):
        logger.error(f"channel counts error: {err}")
        return {"error": "unknown or private"}
    try:
        return {
            "data": {
                "total": data.get("counts", {}).get("people"),
                "bots": data.get("counts", {}).get("bots"),
            }
        }
    except Exception as err:
        logger.error(f"channel count parsing broke: {err}")
        return {"error": "unknown"}


async def user_info(user_id: str) -> dict:
    data = await req("users.profile.get", params={"user": user_id})
    # {profile: {title, real_name, display_name}}
    # there are other fields, but without associated data, prob an extras req
    return data


if __name__ == "__main__":
    import asyncio

    print(asyncio.run(user_info("U0AUBTWBT1N")))
