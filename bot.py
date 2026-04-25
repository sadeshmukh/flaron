from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient
from utils import _env

if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

bot_client = AsyncWebClient(token=_env("XOXB"))
user_client = AsyncWebClient(token=_env("XOXP"))

app = AsyncApp(
    token=_env("XOXB"),
)

BASE_CMD = "/" + _env("BASE_CMD").lstrip("/")


@app.command(BASE_CMD)
async def everything(ack, respond, command):
    await ack()
