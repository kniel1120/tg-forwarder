import os
import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]
SOURCE_CHATS = [int(x.strip()) for x in os.environ.get("SOURCE_CHATS", "").split(",") if x.strip()]
DEST_CHAT = int(os.environ["DEST_CHAT"])


def _parse_user(raw):
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return raw.lstrip("@")


SOURCE_USERS_RAW = [
    u for u in (_parse_user(x) for x in os.environ.get("SOURCE_USERS", "").split(","))
    if u is not None
]

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)


async def _forward(event, tag):
    try:
        await client.forward_messages(DEST_CHAT, event.message)
    except Exception as e:
        print(f"Forward error ({tag}): {e}", flush=True)


async def main():
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("SESSION_STRING invalid or expired — regenerate with session_gen.py")
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} ({me.id})", flush=True)

    resolved_user_ids = []
    for u in SOURCE_USERS_RAW:
        try:
            entity = await client.get_entity(u)
            resolved_user_ids.append(entity.id)
            uname = f"@{entity.username}" if getattr(entity, "username", None) else "(no username)"
            print(f"Resolved user: {entity.first_name} {uname} [{entity.id}]", flush=True)
        except Exception as e:
            print(f"WARNING: failed to resolve user '{u}': {e}", flush=True)

    if SOURCE_CHATS and resolved_user_ids:
        async def handler(event):
            await _forward(event, "user-in-chat")
        client.add_event_handler(
            handler,
            events.NewMessage(chats=SOURCE_CHATS, from_users=resolved_user_ids),
        )
        print(
            f"Mode: filtering {len(resolved_user_ids)} user(s) in {len(SOURCE_CHATS)} chat(s) -> {DEST_CHAT}",
            flush=True,
        )
    elif SOURCE_CHATS:
        async def handler(event):
            await _forward(event, "chat")
        client.add_event_handler(handler, events.NewMessage(chats=SOURCE_CHATS))
        print(
            f"Mode: forwarding all messages from {len(SOURCE_CHATS)} chat(s) -> {DEST_CHAT}",
            flush=True,
        )
    elif resolved_user_ids:
        async def handler(event):
            await _forward(event, "user")
        client.add_event_handler(handler, events.NewMessage(from_users=resolved_user_ids))
        print(
            f"Mode: forwarding from {len(resolved_user_ids)} user(s) anywhere -> {DEST_CHAT}",
            flush=True,
        )
    else:
        print("WARNING: no SOURCE_CHATS or SOURCE_USERS set — nothing will be forwarded", flush=True)

    print("Forwarder running!", flush=True)
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
