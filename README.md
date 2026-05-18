# teleprinter

Convert a Telegram chat history export into a printable PDF of chat bubbles.

```
         Alice  
        ╭──────────────────────────────╮
        │ Hey, are you coming tonight? │
        │                        18:42 │
        ╰──────────────────────────────╯

                                     Bob
                     ╭──────────────────╮
                     │ Yes, around 9 😊 │
                     │            18:45 │ 
                     ╰──────────────────╯   
```

## Requirements

### System
The program uses LaTeX to render the PDF file. 
A working latex installation with lualatex is required if the PDFs are meant to be autocompiled.

```bash
sudo apt install texlive-full fonts-noto-color-emoji poppler-utils
```

| Package               | Purpose                          |
|-----------------------|----------------------------------|
| `texlive-full`        | XeLaTeX compiler                 |
| `fonts-noto-color-emoji` | Emoji rendering in PDFs       |
| `poppler-utils`       | `pdfunite` for merging chunks    |

### Python

Python 3.10+ required.

```bash
pip install pydantic jinja2 pillow tqdm emoji
```

## Installation

```bash
git clone https://github.com/yourname/teleprinter
cd teleprinter
pip install -r requirements.txt
```

## Usage

### Step 1: Export your chat from Telegram Desktop

1. Open the chat in Telegram Desktop
2. Click the three-dot menu → **Export chat history**
3. Select **Both** (JSON & HTML)
4. Choose a destination folder

### Step 2: Run teleprinter

```bash
# Generate .tex files only (no LaTeX required yet)
python -m teleprinter \
    --self-user user123456789 \
    ~/telegram_export \
    ~/output

# Generate and compile to PDF in one step
python -m teleprinter \
    --self-user "Alice" \
    --partner-name "Bob" \
    --compile \
    ~/telegram_export \
    ~/output
```

The final PDF will be at `~/output/chat.pdf`.

### All options

```
positional arguments:
  SOURCE                Directory containing result.json
  TARGET                Output directory (created if absent)

required:
  --self-user ID_OR_NAME
                        Your user ID (e.g. user123456789) or display name.
                        Determines which side of the chat is right-aligned.

optional:
  --partner-name NAME   Display name for the other person when their name
                        is not available in the export. Defaults to their
                        user ID.
  --compile             Run xelatex and pdfunite after generating .tex files.
  --keep-tex            Keep intermediate .tex and per-chunk .pdf files.
  --chunk-size N        Messages per .tex file (default: 1000). Reduce if
                        xelatex runs out of memory on very large chats.
  --output FILENAME     Final PDF filename inside TARGET (default: chat.pdf).
  --verbose, -v         Enable debug logging.
```

### Finding your user ID

If you are unsure of your user ID, run teleprinter with any value for
`--self-user` and it will exit with a list of all sender IDs and names
found in the export:

```
Could not find --self-user 'me' in the export.
Known senders:
  user123456789  (Alice)
  user987654321  (Bob)
```

## What gets rendered

| Message type      | Rendered as                               |
|-------------------|-------------------------------------------|
| Text              | Bubble with sender name and timestamp     |
| Photo             | Image inside bubble, caption below        |
| Sticker           | Thumbnail inside bubble, emoji label      |
| Voice message     | label with duration                       |
| Video             | Thumbnail + "🎬" emoji with duration      |
| GIF / animation   | label (thumbnail if available)            |
| Audio file        | label with filename and duration          |
| File attachment   | label with filename                       |
| Forwarded         | *Forwarded* label above content           |
| Reply             | "↩" indicator before text                 |
| Service messages  | Centred italic note (join, pin, etc.)     |
| Unsupported stuff | Grey placeholders                         |


## Project structure

```
teleprinter/
├── __main__.py       # python -m teleprinter entry point
├── cli.py            # argument parsing and pipeline orchestration
├── models.py         # Pydantic models for the Telegram JSON schema
├── parser.py         # loads and validates result.json
├── processor.py      # converts messages into render-ready dicts
├── text.py           # LaTeX escaping, emoji wrapping, URL handling
├── renderer.py       # Jinja2 → .tex chunk files
├── compiler.py       # xelatex + pdfunite
└── templates/
    └── document.tex.j2   # LaTeX document template
```

## Notes

- **Large chats**: a 111 MB export with ~35 000 messages will process fine
  given enough RAM. The default chunk size of 1000 messages keeps each
  xelatex run manageable. Lower it with `--chunk-size` if needed.

- **Emoji**: Emojis are rendered natively by lualatex as special characters. 
  For this, `fonts-noto-color-emoji` needs to be installed as a system font.
  Without it, emoji characters are silently dropped from the PDF but
  everything else should render correctly.

- **Animated stickers** (`.tgs`): rendered from their JPEG thumbnail since
  LaTeX cannot display Lottie animations.

- **WebP stickers**: rendered from their JPEG thumbnail since LaTeX cannot
  display WebP files directly.

- **Windows / macOS**: the tool is developed and tested on Linux. 
  It may work on other platforms if you can fulfill the dependencies.

## License

MIT
