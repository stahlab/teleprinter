"""
Pydantic models for the Telegram data export schema.

Design notes:
  - extra='ignore' on every model: unknown fields are silently dropped,
    so new Telegram schema additions never crash the tool.
  - populate_by_name=True on Message: allows using both the alias ('from')
    and the Python name ('sender_name') when constructing models.
  - The 'text' field is normalised to a plain string at parse time;
    MessageEntity formatting is intentionally discarded.
  - Many fields are Optional because the schema marks them as conditional.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


### Low-level building blocks 

class MessageEntity(BaseModel):
    """A span of formatted or special text within a message."""
    model_config = ConfigDict(extra='ignore')

    type: str
    text: str = ''


class Location(BaseModel):
    model_config = ConfigDict(extra='ignore')

    latitude: float
    longitude: float


class PollAnswer(BaseModel):
    model_config = ConfigDict(extra='ignore')

    text: str
    voters: int
    chosen: str  # schema uses "true"/"false" strings, not booleans


class Poll(BaseModel):
    model_config = ConfigDict(extra='ignore')

    question: str
    closed: str
    total_voters: int
    answers: list[PollAnswer] = []


class Contact(BaseModel):
    model_config = ConfigDict(extra='ignore')

    first_name: str = ''
    last_name: str = ''
    phone_number: str = ''


class Invoice(BaseModel):
    model_config = ConfigDict(extra='ignore')

    title: str = ''
    description: str = ''
    amount: int = 0
    currency: str = ''


class Giveaway(BaseModel):
    model_config = ConfigDict(extra='ignore')

    quantity: int = 0
    months: int = 0
    until_date: str = ''
    channels: list[int] = []


### Message 

class Message(BaseModel):
    """
    Represents one entry in the messages array of a Chat.

    type='message'  → regular user message
    type='service'  → system event (member joined, title changed, etc.)
    """
    model_config = ConfigDict(extra='ignore', populate_by_name=True)

    id: int
    type: str                           # 'message' | 'service'
    date: datetime
    date_unixtime: Optional[str] = None

    ### Sender (regular messages) 
    # 'from' is a reserved Python keyword; we alias it to sender_name.
    sender_name: Optional[str] = Field(None, alias='from')
    from_id: Optional[str] = None      # e.g. 'user123456'

    ### Actor (service messages) 
    actor: Optional[str] = None
    actor_id: Optional[str] = None

    ### Service message fields 
    action: Optional[str] = None
    members: list[str] = []

    ### Text content 
    # Schema: str  OR  list of (str | MessageEntity).
    # We flatten to plain str here; formatting is intentionally ignored.
    text: str = ''

    ### Media 
    photo: Optional[str] = None         # relative path to photo
    file: Optional[str] = None          # relative path to any file
    thumbnail: Optional[str] = None     # relative path to thumbnail
    media_type: Optional[str] = None    # 'sticker' | 'voice_message' |
                                        # 'video_message' | 'animation' |
                                        # 'video_file' | 'audio_file'
    mime_type: Optional[str] = None
    sticker_emoji: Optional[str] = None     # emoji the sticker represents
    duration_seconds: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None

    ### Audio metadata 
    title: Optional[str] = None
    performer: Optional[str] = None

    ### Rich content (treated as unsupported for now) 
    contact_information: Optional[Contact] = None
    location_information: Optional[Location] = None
    poll: Optional[Poll] = None
    invoice_information: Optional[Invoice] = None
    giveaway_information: Optional[Giveaway] = None

    ### Forwarded / reply 
    forwarded_from: Optional[str] = None
    forwarded_from_id: Optional[str] = None  # present in real exports, absent from schema doc
    reply_to_message_id: Optional[int] = None
    saved_from: Optional[str] = None

    ### Misc 
    edited: Optional[str] = None
    via_bot: Optional[str] = None
    author: Optional[str] = None        # channel post author signature

    reactions: list = []              # emoji reactions; handled but not rendered for now

    @field_validator('text', mode='before')
    @classmethod
    def flatten_text(cls, v: object) -> str:
        """
        Normalise the text field to a plain string.

        Telegram exports text as:
          - a bare string when there are no entities
          - a list of strings and MessageEntity dicts when there are entities

        We concatenate all text content and discard formatting metadata.
        """
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            parts: list[str] = []
            for item in v:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get('text', ''))
            return ''.join(parts)
        return ''

    @property
    def effective_sender_id(self) -> Optional[str]:
        """from_id for regular messages, actor_id for service messages."""
        return self.from_id or self.actor_id

    @property
    def effective_sender_name(self) -> str:
        """Best available display name, falling back to 'Unknown'."""
        return self.sender_name or self.actor or 'Unknown'

    @property
    def is_service(self) -> bool:
        return self.type == 'service'


### Chat and root objects 

class Chat(BaseModel):
    model_config = ConfigDict(extra='ignore')

    id: int
    name: Optional[str] = None  # null in personal chats (privacy / deleted account)
    type: str   # 'personal_chat' | 'private_group' | 'public_supergroup' | …
    messages: list[Message] = []


class Chats(BaseModel):
    model_config = ConfigDict(extra='ignore')

    about: Optional[str] = None
    list: List[Chat] = []


class Root(BaseModel):
    """Represents a full-account export (result.json at the top level)."""
    model_config = ConfigDict(extra='ignore')

    about: Optional[str] = None
    chats: Optional[Chats] = None
    left_chats: Optional[Chats] = None
