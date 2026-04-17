import aiohttp
import logging
from utils import _env
from urllib.parse import quote, urlencode


logger = logging.getLogger(__name__)

XOXC = _env("XOXC")
XOXD = _env("XOXD")
BASE = "https://hackclub.enterprise.slack.com/api/"


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
        return {"error": pretty}
    try:
        return {"data": data.get("role_assignments", [])[0].get("users", [])}
    except Exception:
        logger.error(f"Failed to get managers for {channel_id}")
        return {"data": []}
