"""
Prepare plain text strings for LaTeX output.

Three things happen here:
  1. LaTeX special characters are escaped.
  2. Emoji are detected and wrapped in {\\emojifont ...} so XeLaTeX
     renders them via Noto Color Emoji instead of the main font.
  3. URLs are wrapped in \\url{} so they break across lines cleanly.
  4. Newlines are converted to LaTeX line-break commands.

None of this module knows about messages or bubbles — it only transforms
strings. The processor calls it; the renderer uses the results.
"""

from __future__ import annotations

import re
from typing import Optional

import emoji as emoji_lib


### LaTeX special character escaping 
# Order matters: backslash must be replaced first so that the backslashes
# introduced by later replacements are not themselves re-escaped.

_ESCAPE_STEPS = [
    ('\\', r'\textbackslash{}'),
    ('{',  r'\{'),
    ('}',  r'\}'),
    ('&',  r'\&'),
    ('%',  r'\%'),
    ('$',  r'\$'),
    ('#',  r'\#'),
    ('_',  r'\_'),
    ('~',  r'\textasciitilde{}'),
    ('^',  r'\textasciicircum{}'),
    ('<',  r'\textless{}'),
    ('>',  r'\textgreater{}'),
]


def _escape_plain(text: str) -> str:
    """Escape LaTeX special characters in a plain-text fragment."""
    for char, replacement in _ESCAPE_STEPS:
        text = text.replace(char, replacement)
    return text


### URL detection 

# Matches http(s) and bare www. URLs; stops at whitespace or common trailing
# punctuation that is unlikely to be part of the URL.
_URL_RE = re.compile(
    r'(?:https?://|www\.)'   # scheme or bare www
    r'[^\s<>{}\[\]"\'`]+'    # URL body
    r'(?<![.,;:!?])',         # strip common trailing punctuation
    re.IGNORECASE,
)


### Span-based text processing 
# We collect all "special spans" (URLs and emoji) with their positions in the
# original string, sort them, then process each gap between spans as plain text.

def _collect_spans(text: str) -> list[tuple[int, int, str, str]]:
    """
    Return a sorted list of (start, end, kind, value) for all URLs and emoji.
    Overlapping spans are not expected but are guarded against by skipping
    any span whose start falls within a previously emitted span.
    """
    spans: list[tuple[int, int, str, str]] = []

    for m in _URL_RE.finditer(text):
        spans.append((m.start(), m.end(), 'url', m.group()))

    for e in emoji_lib.emoji_list(text):
        spans.append((e['match_start'], e['match_end'], 'emoji', e['emoji']))

    # Sort by start position; on a tie, URLs take priority over emoji.
    spans.sort(key=lambda s: (s[0], 0 if s[2] == 'url' else 1))

    # Remove overlaps (keep whichever starts first).
    deduplicated: list[tuple[int, int, str, str]] = []
    last_end = 0
    for span in spans:
        if span[0] >= last_end:
            deduplicated.append(span)
            last_end = span[1]

    return deduplicated


def _newlines(text: str) -> str:
    """
    Convert newlines to LaTeX line-break commands.

    Double newlines (paragraph breaks) become \\par.
    Single newlines become \\newline.
    Applied to already-escaped plain text where \\n is still a raw newline.
    """
    text = text.replace('\n\n', r'\par ')
    text = text.replace('\n', r'\newline ')
    return text


### Public API 

def prepare(text: Optional[str]) -> str:
    """
    Convert a raw message text string into a LaTeX-safe string.

    - LaTeX special characters are escaped.
    - Emoji are wrapped in {\\emojifont <emoji>}.
    - URLs are wrapped in \\url{<url>}.
    - Newlines are converted to \\newline / \\par.

    Returns an empty string for None or empty input.
    """
    if not text:
        return ''

    spans = _collect_spans(text)
    result: list[str] = []
    cursor = 0

    for start, end, kind, value in spans:
        # Plain text before this span
        if start > cursor:
            result.append(_newlines(_escape_plain(text[cursor:start])))

        if kind == 'url':
            # \url{} from the LaTeX 'url' package handles line-breaking and
            # most special characters internally — do NOT pre-escape the URL.
            result.append(r'\url{' + value + '}')
        elif kind == 'emoji':
            # Emoji characters don't need LaTeX escaping; just switch font.
            result.append(r'{\emojifont ' + value + '}')

        cursor = end

    # Remaining plain text after the last span
    if cursor < len(text):
        result.append(_newlines(_escape_plain(text[cursor:])))

    return ''.join(result)


def prepare_name(name: Optional[str]) -> str:
    """
    Prepare a sender name for LaTeX.

    Names appear in a small \\bfseries label inside the bubble and may
    contain emoji or special characters, but never newlines.
    Treated identically to prepare() except newline conversion is skipped.
    """
    if not name:
        return ''

    spans = _collect_spans(name)
    result: list[str] = []
    cursor = 0

    for start, end, kind, value in spans:
        if start > cursor:
            result.append(_escape_plain(name[cursor:start]))
        if kind == 'url':
            result.append(r'\url{' + value + '}')
        elif kind == 'emoji':
            result.append(r'{\emojifont ' + value + '}')
        cursor = end

    if cursor < len(name):
        result.append(_escape_plain(name[cursor:]))

    return ''.join(result)
