import aiohttp
import logging
from utils import _env

logger = logging.getLogger(__name__)

XOXC = _env("XOXC")
XOXD = _env("XOXD")
BASE = "https://hackclub.enterprise.slack.com/api/"


async def req(
    path: str, form: dict[str, str] = {}, params: dict[str, str] = {}
) -> dict:
    headers = {"Cookie": "", "Accept": "*/*"}
    params.update({"slack_route": "E09V59WQY1E%3AE09V59WQY1E"})
    paramstring = "&".join(f"{k}:{v}" for k, v in params)
    url = BASE + "path?" + paramstring
    form.update({"token": XOXC})
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(url, data=form) as res:
            data = await res.json()
            if not data.get("ok"):
                return {
                    "error": f"error in {path}: {data.get('error', 'this should never be seen')}"
                }

            return data


async def channel_managers(channel_id: str) -> list[str]:
    data = await req(
        "admin.roles.entity.listAssignments", form={"entity_id": channel_id}
    )
    if data.get("error", ""):
        return []
    try:
        return data.get("role_assignments", [])[0].get("users", [])
    except Exception:
        logger.debug(f"Failed to get managers for {channel_id}")
        return []
