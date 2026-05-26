import os
import time
import hashlib
import asyncio
from collections import OrderedDict
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import MessageEntityCustomEmoji

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]
SOURCE_CHATS = [int(x.strip()) for x in os.environ.get("SOURCE_CHATS", "").split(",") if x.strip()]
DEST_CHAT = int(os.environ["DEST_CHAT"])


def _parse_sender(raw):
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return raw.lstrip("@")


SOURCE_USERS_RAW = [
    u for u in (_parse_sender(x) for x in os.environ.get("SOURCE_USERS", "").split(","))
    if u is not None
]

DEDUP_WINDOW_SECONDS = int(os.environ.get("DEDUP_WINDOW_SECONDS", "600"))
VERBOSE = os.environ.get("VERBOSE", "").strip().lower() in ("1", "true", "yes", "on")
_recent_fingerprints: "OrderedDict[str, float]" = OrderedDict()

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)


def _message_fingerprint(msg):
    text = (msg.text or "").strip()
    media_kind = type(msg.media).__name__ if msg.media else ""
    if not text and not media_kind:
        return None
    return hashlib.md5(f"{text}|{media_kind}".encode("utf-8")).hexdigest()


def _is_duplicate(msg):
    if DEDUP_WINDOW_SECONDS <= 0:
        return False
    fp = _message_fingerprint(msg)
    if fp is None:
        return False
    now = time.time()
    cutoff = now - DEDUP_WINDOW_SECONDS
    while _recent_fingerprints:
        oldest_fp, oldest_ts = next(iter(_recent_fingerprints.items()))
        if oldest_ts >= cutoff:
            break
        _recent_fingerprints.popitem(last=False)
    if fp in _recent_fingerprints:
        return True
    _recent_fingerprints[fp] = now
    return False


async def _forward(event, tag):
    msg = event.message
    if _is_duplicate(msg):
        preview = (msg.text or "").strip().splitlines()[0][:60] if msg.text else "<media>"
        print(f"Skipped duplicate ({tag}): {preview!r}", flush=True)
        return
    try:
        await client.forward_messages(DEST_CHAT, msg)
        return
    except Exception as forward_err:
        print(f"Native forward blocked ({tag}): {forward_err.__class__.__name__}; falling back to copy", flush=True)

    text = msg.text or ""
    entities = [
        ent for ent in (msg.entities or [])
        if not isinstance(ent, MessageEntityCustomEmoji)
    ]
    try:
        if msg.media:
            await client.send_file(
                DEST_CHAT,
                msg.media,
                caption=text,
                formatting_entities=entities or None,
            )
        else:
            await client.send_message(
                DEST_CHAT,
                text,
                formatting_entities=entities or None,
            )
    except Exception as copy_err:
        print(f"Copy-send also failed ({tag}): {copy_err}", flush=True)


async def main():
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("SESSION_STRING invalid or expired — regenerate with session_gen.py")
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} ({me.id})", flush=True)

    sender_ids = set()
    for u in SOURCE_USERS_RAW:
        try:
            entity = await client.get_entity(u)
            sender_ids.add(entity.id)
            kind = type(entity).__name__
            uname = f"@{entity.username}" if getattr(entity, "username", None) else "(no username)"
            label = getattr(entity, "first_name", None) or getattr(entity, "title", "?")
            print(f"Resolved sender: {label} {uname} [{entity.id}, {kind}]", flush=True)
        except Exception as e:
            print(f"WARNING: failed to resolve sender '{u}': {e}", flush=True)

    if SOURCE_CHATS and sender_ids:
        async def handler(event):
            msg = event.message
            matched = (
                msg.post
                or event.sender_id in sender_ids
                or event.sender_id in SOURCE_CHATS
            )
            if VERBOSE:
                preview = (msg.text or "").strip().splitlines()[0][:60] if msg.text else "<media>"
                print(
                    f"DEBUG event: chat={event.chat_id} sender={event.sender_id} "
                    f"post={msg.post} matched={matched} text={preview!r}",
                    flush=True,
                )
            if matched:
                await _forward(event, "matched")
        client.add_event_handler(handler, events.NewMessage(chats=SOURCE_CHATS))
        print(
            f"Mode: filtering channel-posts + {len(sender_ids)} sender(s) in {len(SOURCE_CHATS)} chat(s) -> {DEST_CHAT}",
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
    elif sender_ids:
        async def handler(event):
            if event.sender_id in sender_ids:
                await _forward(event, "sender")
        client.add_event_handler(handler, events.NewMessage())
        print(
            f"Mode: forwarding from {len(sender_ids)} sender(s) anywhere -> {DEST_CHAT}",
            flush=True,
        )
    else:
        print("WARNING: no SOURCE_CHATS or SOURCE_USERS set — nothing will be forwarded", flush=True)

    if DEDUP_WINDOW_SECONDS > 0:
        print(f"Dedup: skip duplicate messages within {DEDUP_WINDOW_SECONDS}s window", flush=True)
    else:
        print("Dedup: disabled", flush=True)
    if VERBOSE:
        print("VERBOSE: logging every received event (set VERBOSE=0 to disable)", flush=True)
    print("Forwarder running!", flush=True)
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
