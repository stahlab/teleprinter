"""
Generate waveform bar data for voice message bubbles.

Since the Telegram JSON export does not include waveform data, and reading
Opus/OGG audio requires heavy external dependencies, we generate a visually
plausible waveform from the message ID and duration.

The output is deterministic: the same message always produces the same bars,
and different messages look meaningfully different from each other.
"""

from __future__ import annotations

import math


# Number of bars in the rendered waveform
WAVEFORM_BARS = 40

# Default bar geometry (pt) — must match to_latex() defaults
_BAR_WIDTH_PT = 2.0
_BAR_GAP_PT   = 1.0

def waveform_width_pt(bars: int       = WAVEFORM_BARS,
                      bar_width: float = _BAR_WIDTH_PT,
                      bar_gap:   float = _BAR_GAP_PT) -> float:
    """Return the total pixel width of the rendered waveform in pt."""
    return bars * (bar_width + bar_gap) - bar_gap


def generate(message_id: int, duration_seconds: int) -> list[float]:
    """
    Return a list of WAVEFORM_BARS floats in the range [0.15, 1.0].

    The pattern is a weighted sum of three sine waves whose frequencies and
    phases are seeded from message_id and duration_seconds. This produces
    an organic-looking envelope that is unique per message.

    Args:
        message_id:        Telegram message ID (used as seed).
        duration_seconds:  Voice message duration (contributes to variation).

    Returns:
        List of normalised amplitude values ready for rendering.
    """
    # Two independent offsets derived from message metadata
    phase_a = (message_id  * 2.3174 + duration_seconds * 1.7319) % (2 * math.pi)
    phase_b = (message_id  * 0.8731 + duration_seconds * 3.1415) % (2 * math.pi)

    raw: list[float] = []
    for i in range(WAVEFORM_BARS):
        t = i / WAVEFORM_BARS
        # Three sine components at different frequencies
        v = (
            0.50 * abs(math.sin(t * math.pi * 3.0  + phase_a)) +
            0.30 * abs(math.sin(t * math.pi * 7.3  + phase_b)) +
            0.20 * abs(math.sin(t * math.pi * 13.1 + phase_a * 0.6))
        )
        raw.append(v)

    # Normalise to [0.15, 1.0] so bars are never invisible
    lo, hi = min(raw), max(raw)
    span = hi - lo if hi > lo else 1.0
    return [(v - lo) / span * 0.85 + 0.15 for v in raw]


def play_button_latex(color: str = 'namecol', radius_pt: float = 8.0) -> str:
    """
    Return a TikZ inline play button: a filled circle with a white triangle.

    Sized to sit neatly next to the waveform bars at the same baseline height.
    """
    r   = radius_pt
    tx0 = -r * 0.30   # triangle left x (slightly inset from centre)
    ty  =  r * 0.50   # triangle half-height
    tx1 =  r * 0.55   # triangle tip x (right)
    return (
        rf'\tikz[baseline=-0.5ex, x=1pt, y=1pt, inner sep=0pt, outer sep=0pt]{{' +
        rf'\fill[{color}] (0,0) circle[radius={r:.1f}pt];' +
        rf'\fill[white] ({tx0:.2f}pt,{ty:.2f}pt) -- ({tx1:.2f}pt,0pt) -- ({tx0:.2f}pt,{-ty:.2f}pt) -- cycle;' +
        r'}}'
    )


def to_latex(bars: list[float],
             bar_width_pt:  float = 2.0,
             bar_gap_pt:    float = 1.0,
             max_height_pt: float = 10.0,
             color:         str   = 'namecol') -> str:
    """
    Convert a list of normalised bar heights into an inline TikZ picture.

    The picture is centred on the text baseline and sized to sit neatly
    inside a tcolorbox bubble alongside the timestamp.

    Args:
        bars:           Output of generate().
        bar_width_pt:   Width of each bar in pt.
        bar_gap_pt:     Gap between bars in pt.
        max_height_pt:  Height of a bar with amplitude 1.0, in pt.
                        Half this extends above the baseline, half below.
        color:          LaTeX color name for the bars.

    Returns:
        A self-contained LaTeX string starting with \\begin{tikzpicture}.
    """
    half = max_height_pt / 2.0
    step = bar_width_pt + bar_gap_pt

    rects: list[str] = []
    for i, amp in enumerate(bars):
        x0 = i * step
        x1 = x0 + bar_width_pt
        h  = amp * half
        rects.append(
            rf'\fill[{color}] ({x0:.2f}pt,{-h:.2f}pt) rectangle ({x1:.2f}pt,{h:.2f}pt);'
        )

    total_width = len(bars) * step - bar_gap_pt

    return (
        rf'\begin{{tikzpicture}}['
        rf'baseline=-0.5ex, x=1pt, y=1pt, '
        rf'inner sep=0pt, outer sep=0pt]'
        + '\n  '
        + '\n  '.join(rects)
        + '\n'
        + rf'\end{{tikzpicture}}'
    )