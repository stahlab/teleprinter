"""
Load and validate a Telegram data export.

Handles two export formats:
  - Single-chat export: result.json IS a Chat object.
  - Full-account export: result.json is a Root object containing a 'chats'
    list and optionally a 'left_chats' list.

Returns a list of Chat objects in both cases. The caller decides which
chat(s) to process.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from models import Chat, Chats, Root

logger = logging.getLogger(__name__)

RESULT_FILENAME = 'result.json'


class ParseError(Exception):
    """Raised when the export file cannot be parsed."""


def load(source_dir: Path) -> list[Chat]:
    """
    Parse result.json in source_dir and return a list of Chat objects.

    Raises:
        FileNotFoundError: if result.json is missing.
        ParseError: if the file is not valid JSON or does not match the schema.
    """
    json_path = source_dir / RESULT_FILENAME

    if not json_path.exists():
        raise FileNotFoundError(
            f"'{RESULT_FILENAME}' not found in {source_dir}.\n"
            "Make sure you point to the directory that contains result.json."
        )

    logger.debug("Loading %s", json_path)

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ParseError(f"result.json is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ParseError("result.json must be a JSON object at the top level.")

    # Distinguish single-chat export from full-account export.
    # A full-account export has a 'chats' key; a single-chat export has
    # 'messages' directly at the top level.
    if 'messages' in data and 'chats' not in data:
        logger.debug("Detected single-chat export.")
        return [_parse_chat(data)]

    logger.debug("Detected full-account export.")
    return _parse_root(data)


def _parse_chat(data: dict) -> Chat:
    try:
        return Chat.model_validate(data)
    except Exception as exc:
        raise ParseError(f"Failed to parse Chat object: {exc}") from exc


def _parse_root(data: dict) -> list[Chat]:
    try:
        root = Root.model_validate(data)
    except Exception as exc:
        raise ParseError(f"Failed to parse Root object: {exc}") from exc

    chats: list[Chat] = []
    if root.chats:
        chats.extend(root.chats.list)
    if root.left_chats:
        chats.extend(root.left_chats.list)

    if not chats:
        raise ParseError("No chats found in the export.")

    logger.debug("Found %d chat(s) in export.", len(chats))
    return chats


def resolve_self_user(chats: list[Chat], self_user: str) -> str:
    """
    Find the from_id that matches the --self-user argument.

    self_user may be:
      - an exact from_id string (e.g. 'user123456')
      - a display name (matched case-insensitively)

    Returns the matching from_id string.

    Raises:
        SystemExit with a helpful error listing known senders if no match.
    """
    # Collect all (from_id, display_name) pairs seen across all chats.
    seen: dict[str, str] = {}  # from_id → best known display name
    for chat in chats:
        for msg in chat.messages:
            fid = msg.effective_sender_id
            if fid and fid not in seen:
                seen[fid] = msg.effective_sender_name

    # Try exact from_id match first.
    if self_user in seen:
        logger.debug("Resolved self_user by ID: %s (%s)", self_user, seen[self_user])
        return self_user

    # Try case-insensitive display name match.
    needle = self_user.lower()
    for fid, name in seen.items():
        if name.lower() == needle:
            logger.debug("Resolved self_user by name: %s → %s", self_user, fid)
            return fid

    # No match — print a helpful error and exit.
    lines = ["Could not find --self-user {!r} in the export.".format(self_user),
             "Known senders:"]
    for fid, name in sorted(seen.items()):
        lines.append(f"  {fid}  ({name})")
    raise SystemExit("\n".join(lines))
