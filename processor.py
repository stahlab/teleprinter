"""
Transform a parsed Chat into a flat list of render-ready dicts.

The output is a list of 'render items', each a plain dict with a 'kind' key:

  kind='date_separator'  → { kind, date_str }
  kind='service'         → { kind, text, time }
  kind='sent'            → { kind, sender_name, time, text, media, is_forwarded,
                              is_reply, edited }
  kind='received'        → same as 'sent'

The template never needs to inspect raw Pydantic models or make side/name
decisions — everything is resolved here.

Media is represented as a nested dict:
  { type, path, thumb_path, width, height, duration, caption,
    sticker_emoji, file_name }

  type is one of:
    'photo'       – JPEG/PNG image (photos/ dir)
    'sticker'     – .webp static sticker
    'sticker_animated' – .tgs animated sticker (we use thumbnail)
    'voice'       – .ogg voice message
    'video'       – video file with thumbnail
    'animation'   – GIF-style mp4 (no thumbnail guaranteed)
    'audio'       – audio file
    'file'        – generic file attachment
    'unsupported' – anything else
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from tqdm import tqdm

from models import Chat, Message

logger = logging.getLogger(__name__)


###  Config passed in from the orchestrator 

@dataclass
class ProcessorConfig:
    self_user_id: str        # e.g. 'user123456789'
    source_dir: Path         # root of the export (where result.json lives)
    partner_name: str = 'Unknown'  # display name for null-from contacts


###  Media classification 

def _classify_sticker(msg) -> str:
    """Animated stickers (.tgs) are handled differently from static (.webp)."""
    if msg.file and msg.file.endswith('.tgs'):
        return 'sticker_animated'
    return 'sticker'


_MEDIA_TYPE_MAP = {
    'sticker':       _classify_sticker,
    'voice_message': 'voice',
    'video_message': 'video',
    'video_file':    'video',
    'animation':     'animation',
    'audio_file':    'audio',
}


def _media_type(msg: Message) -> Optional[str]:
    """
    Determine the normalised media type for a message, or None if no media.
    """
    if msg.photo:
        return 'photo'

    if msg.media_type:
        classifier = _MEDIA_TYPE_MAP.get(msg.media_type)
        if classifier is None:
            return 'unsupported'
        if callable(classifier):
            return classifier(msg)
        return classifier

    # A file with no media_type is a generic attachment.
    if msg.file:
        return 'file'

    return None


def _resolve(source_dir: Path, rel_path: Optional[str]) -> Optional[Path]:
    """Resolve a relative export path to an absolute Path, or None."""
    if not rel_path:
        return None
    p = source_dir / rel_path
    if not p.exists():
        logger.warning("Media file not found: %s", p)
        return None
    return p


###  Service message description 

_SERVICE_DESCRIPTIONS = {
    'create_group':              lambda m: f"{m.actor or 'Someone'} created the group \"{m.title or ''}\"",
    'edit_group_title':          lambda m: f"{m.actor or 'Someone'} changed the group name to \"{m.title or ''}\"",
    'edit_group_photo':          lambda m: f"{m.actor or 'Someone'} updated the group photo",
    'delete_group_photo':        lambda m: f"{m.actor or 'Someone'} removed the group photo",
    'invite_members':            lambda m: f"{m.actor or 'Someone'} invited {', '.join(m.members)}",
    'remove_members':            lambda m: f"{m.actor or 'Someone'} removed {', '.join(m.members)}",
    'join_group_by_link':        lambda m: f"{m.actor or 'Someone'} joined via invite link",
    'join_group_by_request':     lambda m: f"{m.actor or 'Someone'} joined by request",
    'pin_message':               lambda m: f"{m.actor or 'Someone'} pinned a message",
    'clear_history':             lambda m: f"{m.actor or 'Someone'} cleared the chat history",
    'migrate_to_supergroup':     lambda m: "Group was upgraded to a supergroup",
    'migrate_from_group':        lambda m: "Migrated from a group",
    'phone_call':                lambda m: _describe_call(m),
    'joined_telegram':           lambda m: f"{m.actor or 'Someone'} joined Telegram",
    'set_messages_ttl':          lambda m: f"Auto-delete timer changed",
    'edit_chat_theme':           lambda m: f"{m.actor or 'Someone'} changed the chat theme",
    'topic_created':             lambda m: f"Topic \"{m.title or ''}\" created",
    'topic_edit':                lambda m: f"Topic edited",
    'suggest_profile_photo':     lambda m: f"{m.actor or 'Someone'} suggested a profile photo",
    'send_premium_gift':         lambda m: f"{m.actor or 'Someone'} sent a Telegram Premium gift",
}


def _describe_call(m: Message) -> str:
    if m.discard_reason == 'missed':
        return f"Missed call from {m.actor or 'someone'}"
    if m.discard_reason == 'busy':
        return f"Call declined"
    dur = m.duration_seconds or 0
    mins, secs = divmod(dur, 60)
    return f"Call – {mins}m {secs:02d}s" if mins else f"Call – {secs}s"


def _service_text(msg: Message) -> str:
    handler = _SERVICE_DESCRIPTIONS.get(msg.action or '')
    if handler:
        try:
            return handler(msg)
        except Exception:
            pass
    return f"[{msg.action or 'service event'}]"


###  Main processing 

def process(chat: Chat, cfg: ProcessorConfig) -> list[dict]:
    """
    Convert a Chat into a flat list of render-ready item dicts.

    Date separators are injected automatically when the calendar date changes.
    """
    items: list[dict] = []
    last_date: Optional[date] = None

    for msg in tqdm(chat.messages, desc='Processing messages', unit='msg'):

        msg_date = msg.date.date()

        ###  Date separator 
        if msg_date != last_date:
            items.append({
                'kind': 'date_separator',
                'date_str': msg.date.strftime('%-d %B %Y'),  # e.g. "4 January 2021"
            })
            last_date = msg_date

        ###  Service message 
        if msg.is_service:
            items.append({
                'kind':   'service',
                'text':   _service_text(msg),
                'time':   msg.date.strftime('%H:%M'),
            })
            continue

        ###  Regular message 
        side = 'sent' if msg.from_id == cfg.self_user_id else 'received'

        sender = _resolve_name(msg, cfg)

        media = _build_media(msg, cfg.source_dir)

        items.append({
            'kind':         side,
            'sender_name':  sender,
            'time':         msg.date.strftime('%H:%M'),
            'text':         msg.text,
            'media':        media,
            'is_forwarded': msg.forwarded_from is not None,
            'is_reply':     msg.reply_to_message_id is not None,
            'edited':       msg.edited is not None,
        })

    logger.info("Processed %d messages into %d render items.", len(chat.messages), len(items))
    return items


def _resolve_name(msg: Message, cfg: ProcessorConfig) -> str:
    """
    Return the best display name for a message sender.

    Priority:
      1. The 'from' field if non-null
      2. --partner-name if the sender is not the self user
      3. The raw from_id as last resort
    """
    if msg.sender_name:
        return msg.sender_name
    if msg.from_id == cfg.self_user_id:
        # Self user with a null name is unusual but handle it gracefully.
        return cfg.self_user_id
    return cfg.partner_name if cfg.partner_name != 'Unknown' else (msg.from_id or 'Unknown')


def _build_media(msg: Message, source_dir: Path) -> Optional[dict]:
    """
    Build a media descriptor dict for a message, or None if no media.
    """
    mtype = _media_type(msg)
    if mtype is None:
        return None

    # Resolve file paths
    if mtype == 'photo':
        main_path = _resolve(source_dir, msg.photo)
        thumb_path = None
    else:
        main_path = _resolve(source_dir, msg.file)
        thumb_path = _resolve(source_dir, msg.thumbnail)

    # For animated stickers we fall back to the thumbnail since we can't
    # render .tgs in LaTeX.
    if mtype == 'sticker_animated' and thumb_path:
        display_path = thumb_path
    else:
        display_path = main_path

    return {
        'type':          mtype,
        'path':          display_path,      # Path or None
        'thumb_path':    thumb_path,        # Path or None (for video overlays etc.)
        'width':         msg.width,
        'height':        msg.height,
        'duration':      msg.duration_seconds,
        'caption':       msg.text or None,  # text accompanying media
        'sticker_emoji': msg.sticker_emoji,
        'file_name':     _file_name(msg),
    }


def _file_name(msg: Message) -> Optional[str]:
    """Extract a display filename from the file path."""
    if msg.file:
        return Path(msg.file).name
    if msg.photo:
        return Path(msg.photo).name
    return None


###  Chunking 

def chunk(items: list[dict], size: int) -> list[list[dict]]:
    """
    Split render items into chunks of at most `size` *messages*
    (date separators and service messages don't count toward the limit).

    Each chunk always starts cleanly — if the first real item in a chunk
    would be on a date that was already announced in the previous chunk,
    the date separator is repeated so each .tex file is self-contained.
    """
    if size <= 0:
        raise ValueError("Chunk size must be positive.")

    chunks: list[list[dict]] = []
    current: list[dict] = []
    msg_count = 0
    last_date_item: Optional[dict] = None

    for item in items:
        is_message = item['kind'] in ('sent', 'received')

        if is_message and msg_count >= size:
            chunks.append(current)
            current = []
            msg_count = 0
            # Re-emit the last date separator so the new chunk has context.
            if last_date_item:
                current.append(last_date_item)

        if item['kind'] == 'date_separator':
            last_date_item = item

        current.append(item)

        if is_message:
            msg_count += 1

    if current:
        chunks.append(current)

    return chunks
