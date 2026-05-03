import asyncio
import logging
import re

import slack_bolt
from slack_bolt.async_app import AsyncApp, AsyncAck, AsyncRespond
from slack_sdk.web.async_client import AsyncWebClient
from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

logging.basicConfig(level=logging.INFO, format="FLARON [%(name)s]: %(message)s")

from cache import get_all_cached_name_to_id
from private import cid_by_name_private, cname_private
from userbot import app_info, channel_info, emoji_info, install_info, user_info_edge
from utils import _env

user_client = AsyncWebClient(token=_env("XOXP"))

app = AsyncApp(
    token=_env("XOXB"),
)


BASE_CMD = "/" + _env("BASE_CMD").lstrip("/")
ADMIN_KEY = _env("ADMIN_KEY")

error_message = lambda err: "Oh no! Looks like something went wrong: " + err


@app.command(BASE_CMD)
async def everything(ack: AsyncAck, respond: AsyncRespond, command: dict):
    await ack()
    tokens = command.get("text", "").strip().split()
    if not tokens or tokens[0] == "help":
        return await respond(
            "Usage:\n"
            f"`{BASE_CMD} <command> [args]`\n\n"
            "Available commands:\n"
            "- `ping`\n"
            "- `emoji <name>`: Fetches information about a specific emoji.\n"
            "- `app @bot`: Fetches information about a specific bot application.\n"
        )

    def resp_err(err: str):
        return respond(error_message(err))

    cmd = tokens[0]
    args = tokens[1:]
    if cmd == "ping":
        await respond("pong")

    elif cmd == "emoji":
        if len(args) != 1:
            return await respond(f"Usage: `{BASE_CMD} emoji <name>`")
        emoji = args[0].strip(":")
        info = await emoji_info(emoji)
        if info.get("error"):
            return await resp_err(info["error"])
        info = info.get("data", {})
        synonym_text = (
            "Synonyms: " + ", ".join(info.get("synonyms", []))
            if len(info.get("synonyms", [])) > 1
            else ""
        )
        await respond(
            f"*{emoji} (:{emoji}:)*\n"
            + (
                f"Alias for :{info.get('alias_for')}:"
                if info.get("alias_for")
                else "" f"Made by <@{info.get('user_id')}> | "
            )
            + (synonym_text if len(info.get("synonyms", [])) > 0 else "")
        )
    elif cmd == "app":
        if len(args) != 1:
            return await respond(f"Usage: `{BASE_CMD} app @bot")
        identifier = args[0]
        # user -> app data
        if not (m := re.fullmatch(r"<@([A-Z0-9]+)(?:\|[^>]*)?>", identifier)):
            return await respond("no mention found?")
        user_id = m.group(1)
        if (userinfo := await user_info_edge(user_id)).get("error"):
            return await resp_err(userinfo.get("error", "unknown"))
        userinfo = userinfo.get("data", {})
        if not userinfo.get("is_bot"):
            return await respond("That's not a bot?")
        # stuff we care about:
        # marketplace link, creator, installer MENTIONS, channel count
        app_id = userinfo.get("app_id")
        install_info_data = await install_info(app_id)

        if install_info_data.get("error"):
            return await resp_err(install_info_data.get("error", "unknown"))
        install_info_data = install_info_data.get("data", {})
        installers = install_info_data.get("installers", [])
        creator_id = install_info_data.get("creator", "")
        app_info_data = await app_info(app_id, userinfo.get("bot_id"))
        if app_info_data.get("error"):
            return await resp_err(app_info_data.get("error", "unknown"))
        app_info_data = app_info_data.get("data", {})
        await respond(
            f"*{app_info_data.get('name', 'Unknown App')}*\n"
            f"Created by <@{creator_id}> | "
            f"Installed by {', '.join([f'<@{inst.get('id')}>' for inst in installers])}\n"
            f"Channels: {app_info_data.get('count_in', 0)} | "
            f"Marketplace: https://hackclub.slack.com/marketplace/{app_id}\n"
            + (
                f"Description: ```{app_info_data.get('description', 'No description')}```"
                if app_info_data.get("description")
                else ""
            )
        )
    elif cmd == "search":
        if len(args) < 1:
            return await respond(f"search ~key~ q")
        query = args[0]
        if command.get("user_id") != "U08PUHSMW4V":
            logging.info("unauthorized: " + command.get("user_id", ""))
            if not command.get("user_id"):
                logging.warning("I love testing in prod: " + str(command))

            return await respond("who do you think you are")
        query_lower = query.lower()
        all_channels = get_all_cached_name_to_id()
        matches = [
            (name, cid)
            for name, cid in all_channels.items()
            if query_lower in name.lower()
        ]
        if not matches:
            return await respond(f"none matching `{query}`.")
        matches.sort(key=lambda x: x[0])
        lines = [f"`#{name}` ({cid})" for name, cid in matches[:50]]
        suffix = f"\n_…and {len(matches) - 50} more_" if len(matches) > 50 else ""
        await respond(
            f"*{len(matches)} match(es) for `{query}`:*\n" + "\n".join(lines) + suffix
        )

    else:
        await respond("???")


# message shortcut
@app.shortcut("reveal_channels")
async def reveal_channels(
    ack: AsyncAck, shortcut: dict, client: AsyncWebClient, respond: AsyncRespond
):
    await ack()
    logging.info(
        (c := shortcut.get("user", {}).get("name"))
        + ":"
        + (shortcut.get("channel", {}).get("id"))
    )

    content = shortcut.get("message", {}).get("text", "")
    if not content:
        return await respond(
            text="Couldn't find any content in the message :(",
            response_type="ephemeral",
        )
    # cids -> names, render as #name?
    cids = re.findall(r"C[A-Z0-9]{6,}", content)
    if not cids:
        return await respond(
            text="Couldn't find any channel IDs in the message :(",
            response_type="ephemeral",
        )

    async def cname(cid) -> str:
        cinfo = await channel_info(cid)
        if cinfo.get("error"):
            return (await cname_private(cid)).get("name", cid)
        return cinfo.get("data", {}).get("name", cid)

    names = [await cname(cid) for cid in cids]  # type: ignore
    if thread_ts := shortcut.get("message", {}).get("ts"):
        await respond(
            text="Channels mentioned: " + ", ".join(f"`#{name}`" for name in names),
            response_type="ephemeral",
            thread_ts=thread_ts,
        )
        return
    await respond(
        text="Channels mentioned: " + ", ".join(f"`#{name}`" for name in names),
        response_type="ephemeral",
    )


async def main():
    auth = await app.client.auth_test()
    user_id = auth.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise RuntimeError("auth_test did not return user_id")
    logging.info(f"Running with user ID: {user_id}")

    handler: AsyncSocketModeHandler = AsyncSocketModeHandler(app, _env("XAPP"))
    await handler.start_async()


if __name__ == "__main__":

    asyncio.run(main())
