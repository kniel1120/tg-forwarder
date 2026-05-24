import os
import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]
SOURCE_CHATS = [int(x.strip()) for x in os.environ["SOURCE_CHATS"].split(",") if x.strip()]
DEST_CHAT = int(os.environ["DEST_CHAT"])

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)


@client.on(events.NewMessage(chats=SOURCE_CHATS))
async def handler(event):
    try:
        await client.forward_messages(DEST_CHAT, event.message)
    except Exception as e:
        print(f"Forward error: {e}", flush=True)


async def main():
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("SESSION_STRING invalid or expired — regenerate with session_gen.py")
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} ({me.id})", flush=True)
    print(f"Watching {len(SOURCE_CHATS)} source chat(s) -> {DEST_CHAT}", flush=True)
    print("Forwarder running!", flush=True)
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
