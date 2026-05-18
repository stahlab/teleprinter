"""
Prepare render items and write .tex chunk files via Jinja2.

Responsibilities:
  - Apply text.prepare() / text.prepare_name() to all string fields
  - Compute image display widths (from JSON dimensions or Pillow fallback)
  - Create LaTeX-safe paths for media files: symlinks for JPEG/PNG, converts WebP to JPEG
  - Render the Jinja2 template for each chunk and write to disk

Text preparation intentionally happens here rather than in the processor
so that processor output remains clean Python data (easier to debug/test).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import jinja2

import text as text_module
from config import ThemeConfig

logger = logging.getLogger(__name__)

### Page geometry constants
# A4 with left=1.2cm, right=1.2cm margins → textwidth ≈ 527pt
# Bubble max width (\bw) = 0.70 * textwidth ≈ 369pt

_TEXTWIDTH_PT   = 527.0
_BW_PT          = _TEXTWIDTH_PT * 0.70   # ≈ 369pt
_MAX_IMAGE_H_PT = 400.0


### Helpers

def _compute_display_width(width: Optional[int], height: Optional[int],
                            path: Optional[Path]) -> str:
    """
    Return a LaTeX dimension string (e.g. '246pt') for displaying an image.

    Uses the JSON width/height fields when available (reliable for Telegram
    exports). Falls back to opening the file with Pillow if needed.
    Scales from pixels to points assuming ~0.75pt per pixel, capped at
    the maximum bubble width and a maximum height.
    """
    w, h = width, height

    if (not w or not h) and path and path.exists():
        try:
            from PIL import Image
            with Image.open(path) as img:
                w, h = img.size
        except Exception:
            pass

    if not w or not h:
        return f'{int(_BW_PT * 0.5)}pt'   # safe fallback: half bubble width

    w_pt = w * 0.75
    h_pt = h * 0.75

    if w_pt > _BW_PT:
        h_pt *= _BW_PT / w_pt
        w_pt  = _BW_PT
    if h_pt > _MAX_IMAGE_H_PT:
        w_pt *= _MAX_IMAGE_H_PT / h_pt
        h_pt  = _MAX_IMAGE_H_PT

    return f'{max(w_pt, 60.0):.0f}pt'


# Magic bytes for image format detection
_JPEG_MAGIC = b'\xff\xd8\xff'
_PNG_MAGIC  = b'\x89PNG'
_WEBP_MAGIC = b'RIFF'   # followed by 4 bytes size then b'WEBP'

def _actual_format(path: Path) -> str:
    """
    Return the actual image format by inspecting magic bytes,
    regardless of the file extension.
    Returns 'jpeg', 'png', 'webp', or 'unknown'.
    """
    try:
        with open(path, 'rb') as f:
            header = f.read(12)
        if header[:3] == _JPEG_MAGIC:
            return 'jpeg'
        if header[:4] == _PNG_MAGIC:
            return 'png'
        if header[:4] == _WEBP_MAGIC and header[8:12] == b'WEBP':
            return 'webp'
    except OSError:
        pass
    return 'unknown'


def _sanitize_media_path(original: Path, media_dir: Path) -> Optional[Path]:
    """
    Return a LaTeX-safe path for an image file.

    Handles two problems:
      1. Filenames with spaces/parens that break \\includegraphics.
         Fixed by creating a symlink with a safe name.
      2. Files with a .jpg extension that are actually WebP or PNG
         (Telegram sometimes does this for sticker thumbnails).
         Fixed by converting to a real JPEG using Pillow.

    LuaLaTeX supports JPEG and PNG natively. WebP is not supported.
    """
    if not original or not original.exists():
        return None

    media_dir.mkdir(parents=True, exist_ok=True)

    parent_prefix = re.sub(r'[^a-zA-Z0-9]', '_', original.parent.name)
    safe_stem     = re.sub(r'[^a-zA-Z0-9._-]', '_', original.stem)

    fmt = _actual_format(original)

    # If the file is WebP (regardless of extension), convert to JPEG.
    # PNG is fine for LuaLaTeX so we keep it as-is.
    if fmt == 'webp':
        safe_name = f'{parent_prefix}_{safe_stem}.jpg'
        out_path  = media_dir / safe_name
        if not out_path.exists():
            try:
                from PIL import Image
                with Image.open(original) as img:
                    rgb = img.convert('RGB')
                    rgb.save(out_path, 'JPEG', quality=90)
                logger.debug("Converted WebP → JPEG: %s", out_path.name)
            except Exception as exc:
                logger.warning("Could not convert %s to JPEG: %s", original.name, exc)
                return None
        return out_path

    # For JPEG and PNG: symlink with a safe name.
    safe_suffix = re.sub(r'[^a-zA-Z0-9._-]', '_', original.suffix)
    safe_name   = f'{parent_prefix}_{safe_stem}{safe_suffix}'
    link_path   = media_dir / safe_name

    if not link_path.exists():
        try:
            link_path.symlink_to(original.resolve())
        except OSError as exc:
            logger.warning("Symlink failed (%s); using original path.", exc)
            return original

    return link_path


### Renderer

class Renderer:
    def __init__(self, target_dir: Path, template_dir: Path, theme: ThemeConfig = None):
        self.target_dir = target_dir
        self.target_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir = target_dir / 'media'

        self.theme = theme or ThemeConfig()

        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            block_start_string='(%',
            block_end_string='%)',
            variable_start_string='((',
            variable_end_string='))',
            comment_start_string='(#',
            comment_end_string='#)',
            trim_blocks=True,
            lstrip_blocks=True,
            autoescape=False,
            keep_trailing_newline=True,
        )
        # Make theme available globally inside templates (including macros)
        self.env.globals['theme'] = self._build_theme_dict()
        self.template = self.env.get_template('document.tex.j2')

    def _build_theme_dict(self) -> dict:
        """Convert ThemeConfig to a plain dict for the Jinja2 template."""
        t = self.theme
        bg_tex = None
        if t.background:
            safe = _sanitize_media_path(t.background, self.media_dir)
            bg_tex = str(safe) if safe else None
        return {
            'sent_color':            t.sent_color,
            'recv_color':            t.recv_color,
            'chat_bg_color':         t.chat_bg_color,
            'name_color':            t.name_color,
            'background_tex':        bg_tex,
            'page_size_latex':       t.page_size_latex,
            'font_size':             t.font_size,
            'bubble_width_fraction': t.bubble_width_fraction,
            'show_service_messages': t.show_service_messages,
            'show_edited_marker':    t.show_edited_marker,
        }

    def render_chunk(self, items: list[dict], chunk_num: int) -> Path:
        """Prepare items, render template, write .tex file. Returns the path."""
        prepared = [self._prepare_item(item) for item in items]
        content  = self.template.render(items=prepared)
        out_path = self.target_dir / f'chunk_{chunk_num:03d}.tex'
        out_path.write_text(content, encoding='utf-8')
        logger.debug("Wrote %s", out_path)
        return out_path

    ### Item preparation

    def _prepare_item(self, item: dict) -> dict:
        item = item.copy()
        kind = item['kind']

        if kind == 'date_separator':
            item['date_str'] = text_module.prepare_name(item['date_str'])

        elif kind == 'service':
            item['text'] = text_module.prepare(item['text'])

        else:   # 'sent' | 'received'
            item['sender_name'] = text_module.prepare_name(item['sender_name'])
            item['text']        = text_module.prepare(item['text'])

            if item.get('media'):
                item['media'] = self._prepare_media(item['media'])

            # Bubble width: match image size or use full \bw for text
            media = item.get('media')
            if media and 'display_width' in media:
                item['bubble_width'] = media['display_width']
            else:
                item['bubble_width'] = r'\bw'

        return item

    def _prepare_media(self, media: dict) -> dict:
        media = media.copy()
        mtype = media.get('type', '')

        # Prepare text fields
        if media.get('caption'):
            media['caption'] = text_module.prepare(media['caption'])
        if media.get('file_name'):
            media['file_name'] = text_module.prepare_name(media['file_name'])
        if media.get('sticker_emoji'):
            media['sticker_emoji_tex'] = text_module.prepare_name(media['sticker_emoji'])

        # Convert waveform bar data to a LaTeX TikZ snippet + play button
        if media.get('waveform'):
            from waveform import to_latex, play_button_latex, waveform_width_pt
            media['waveform_tex']    = to_latex(media['waveform'])
            media['play_button_tex'] = play_button_latex()

            # Compute tight bubble width:
            #   play button (16pt diam + 4pt gap)
            #   + waveform
            #   + duration label (~22pt)
            #   + bubble padding left+right (16pt)
            play_w    = 16.0 + 4.0
            wf_w      = waveform_width_pt()
            dur_w     = 22.0
            padding   = 16.0
            media['display_width'] = f'{play_w + wf_w + dur_w + padding:.0f}pt'

        # Sanitize paths — creates safe symlinks in target_dir/media/
        main_path  = media.get('path')
        thumb_path = media.get('thumb_path')

        safe_main  = _sanitize_media_path(main_path,  self.media_dir) if main_path  else None
        safe_thumb = _sanitize_media_path(thumb_path, self.media_dir) if thumb_path else None

        media['path_tex']       = str(safe_main)  if safe_main  else None
        media['thumb_path_tex'] = str(safe_thumb) if safe_thumb else None

        # For stickers (both static and animated), display the thumbnail.
        # Static stickers are .webp which LaTeX cannot render;
        # animated stickers are .tgs which LaTeX also cannot render.
        # Both have a .jpg thumbnail provided by Telegram.
        if mtype in ('sticker', 'sticker_animated'):
            media['display_path_tex'] = media['thumb_path_tex'] or media['path_tex']
        else:
            media['display_path_tex'] = media['path_tex']

        # Compute display width for image-like media
        if mtype in ('photo', 'sticker', 'sticker_animated'):
            media['display_width'] = _compute_display_width(
                media.get('width'),
                media.get('height'),
                main_path,
            )

        return media