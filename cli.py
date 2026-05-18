"""
Command-line interface and pipeline orchestrator for teleprinter.

Wires together parser → processor → renderer → compiler in the right order,
validates all preconditions before touching the export data, and provides
clear error messages for every failure mode.

Usage:
    python -m teleprinter --self-user user123456789 /path/to/export /path/to/output
    python -m teleprinter --self-user "Alice" --compile /path/to/export /path/to/output
    python -m teleprinter --create-config
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from tqdm import tqdm


### Logging setup 

def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format='%(levelname)s: %(message)s',
        level=level,
    )


### Startup checks 

_BINARY_INSTALL_HINTS = {
    'lualatex': 'sudo apt install texlive-full',
    'pdfunite': 'sudo apt install poppler-utils',
}


def check_binaries(names: list[str]) -> None:
    """
    Verify that all required system binaries are on PATH.
    Exits immediately with a helpful message if any are missing.
    Called before any processing begins.
    """
    missing = [n for n in names if not shutil.which(n)]
    if not missing:
        return

    lines = ['The following required programs were not found on PATH:']
    for name in missing:
        hint = _BINARY_INSTALL_HINTS.get(name, '')
        suffix = f'  →  {hint}' if hint else ''
        lines.append(f'  {name}{suffix}')
    sys.exit('\n'.join(lines))


def check_source_dir(source: Path) -> None:
    """Exit with a clear message if the source directory or result.json is missing."""
    if not source.is_dir():
        sys.exit(f"Source directory not found: {source}")
    if not (source / 'result.json').exists():
        sys.exit(
            f"'result.json' not found in {source}.\n"
            "Make sure you point to the directory that contains result.json."
        )


### Argument parser 

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='teleprinter',
        description='Convert a Telegram chat export into a PDF of chat bubbles.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  # Generate a starter config file:
  python -m teleprinter --create-config

  # Generate .tex files only:
  python -m teleprinter --self-user user123456789 ~/export ~/output

  # Generate and compile to PDF:
  python -m teleprinter --self-user "Alice" --compile ~/export ~/output

  # Full run with config file:
  python -m teleprinter \\
      --self-user user123456789 \\
      --partner-name "Bob" \\
      --config ~/export/teleprinter.toml \\
      --compile \\
      ~/export ~/output
""",
    )

    p.add_argument(
        'source',
        type=Path,
        metavar='SOURCE',
        nargs='?',
        help='Directory containing result.json (the Telegram export folder)',
    )
    p.add_argument(
        'target',
        type=Path,
        metavar='TARGET',
        nargs='?',
        help='Output directory (created if it does not exist)',
    )
    p.add_argument(
        '--self-user',
        default=None,
        metavar='ID_OR_NAME',
        help=(
            "Your user ID (e.g. 'user123456789') or display name. "
            "Determines which side of the chat is right-aligned."
        ),
    )
    p.add_argument(
        '--partner-name',
        default=None,
        metavar='NAME',
        help=(
            "Display name for the other person when their 'from' field is null. "
            "Overrides the partner_name field in the config file."
        ),
    )
    p.add_argument(
        '--config',
        type=Path,
        default=None,
        metavar='PATH',
        help=(
            "Path to a TOML config file. If not given, teleprinter looks for "
            "teleprinter.toml in SOURCE automatically."
        ),
    )
    p.add_argument(
        '--create-config',
        nargs='?',
        const=Path('teleprinter.toml'),
        metavar='PATH',
        help=(
            "Write a default config file and exit. "
            "PATH defaults to ./teleprinter.toml."
        ),
    )
    p.add_argument(
        '--compile',
        action='store_true',
        help='Run lualatex on each chunk and stitch with pdfunite after generation.',
    )
    p.add_argument(
        '--keep-tex',
        action='store_true',
        help=(
            'Keep intermediate .tex and per-chunk .pdf files after compilation. '
            'Has no effect without --compile.'
        ),
    )
    p.add_argument(
        '--chunk-size',
        type=int,
        default=1000,
        metavar='N',
        help='Maximum number of messages per .tex file (default: 1000).',
    )
    p.add_argument(
        '--output',
        default='chat.pdf',
        metavar='FILENAME',
        help="Final PDF filename inside TARGET (default: chat.pdf).",
    )
    p.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable debug logging.',
    )

    return p


### Config loading 

def _load_theme(args: argparse.Namespace) -> object:
    """
    Load ThemeConfig from file (if any) and apply CLI overrides.

    Search order for the config file:
      1. --config PATH (explicit)
      2. SOURCE/teleprinter.toml (auto-discovery)
      3. No config file → all defaults
    """
    from config import ThemeConfig, load as load_config

    config_path = args.config
    if config_path is None and args.source:
        candidate = args.source / 'teleprinter.toml'
        if candidate.exists():
            config_path = candidate

    if config_path:
        logging.getLogger(__name__).info("Loading config from %s", config_path)
        theme = load_config(config_path)
    else:
        theme = ThemeConfig()

    # CLI --partner-name overrides config file partner_name
    if args.partner_name:
        theme.partner_name = args.partner_name

    return theme


### Pipeline 

def run(args: argparse.Namespace) -> None:
    """Execute the full pipeline according to parsed CLI arguments."""
    _setup_logging(args.verbose)
    log = logging.getLogger(__name__)

    ### Validate required positional args (not needed for --create-config) 
    if not args.source:
        sys.exit("error: SOURCE is required. Use --help for usage.")
    if not args.target:
        sys.exit("error: TARGET is required. Use --help for usage.")
    if not args.self_user:
        sys.exit("error: --self-user is required. Use --help for usage.")

    ### Precondition checks 
    check_source_dir(args.source)

    if args.compile:
        check_binaries(['lualatex', 'pdfunite'])

    args.target.mkdir(parents=True, exist_ok=True)

    ### Load theme config 
    try:
        theme = _load_theme(args)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(f"Config error: {exc}")

    ### Imports (deferred so --help is instant) 
    from models    import Chat
    from parser    import load, resolve_self_user
    from processor import ProcessorConfig, process, chunk
    from renderer  import Renderer

    ### Parse 
    log.info("Loading export from %s ...", args.source)
    chats = load(args.source)

    if len(chats) > 1:
        lines = [
            f"Found {len(chats)} chats in the export. "
            "This tool currently processes one chat at a time.\n",
            "Chats found:",
        ]
        for c in chats:
            lines.append(f"  [{c.type}] id={c.id}  name={c.name or '(no name)'}  "
                         f"messages={len(c.messages)}")
        lines.append(
            "\nRe-export a single chat via Telegram Desktop "
            "('Export chat history' from within the chat)."
        )
        sys.exit('\n'.join(lines))

    chat = chats[0]
    log.info(
        "Chat: %r  type=%s  messages=%d",
        chat.name or '(no name)', chat.type, len(chat.messages),
    )

    ### Resolve self-user 
    self_user_id = resolve_self_user(chats, args.self_user)
    log.info("Self user resolved to: %s", self_user_id)

    ### Determine partner display name 
    # Priority: --partner-name CLI > config file partner_name > user ID fallback
    partner_name = theme.partner_name or 'Unknown'

    ### Process 
    cfg = ProcessorConfig(
        self_user_id=self_user_id,
        source_dir=args.source,
        partner_name=partner_name,
    )
    items  = process(chat, cfg)
    chunks = chunk(items, size=args.chunk_size)
    log.info(
        "%d render items → %d chunk(s) of max %d messages",
        len(items), len(chunks), args.chunk_size,
    )

    ### Render 
    template_dir = Path(__file__).parent / 'templates'
    renderer     = Renderer(
        target_dir=args.target,
        template_dir=template_dir,
        theme=theme,
    )

    log.info("Rendering %d chunk(s) to %s ...", len(chunks), args.target)
    tex_files = []
    for i, ch in enumerate(
        tqdm(chunks, desc='Rendering chunks', unit='chunk'), start=1
    ):
        tex_files.append(renderer.render_chunk(ch, i))

    if not args.compile:
        log.info(
            "Done. %d .tex file(s) written to %s\n"
            "To compile manually: lualatex <chunk>.tex  (then pdfunite)",
            len(tex_files), args.target,
        )
        return

    ### Compile 
    from compiler import compile_all, stitch, cleanup_chunk_pdfs, CompilerError

    log.info("Compiling %d chunk(s) with lualatex ...", len(tex_files))
    try:
        pdf_files = compile_all(tex_files, keep_tex=args.keep_tex)
    except CompilerError as exc:
        sys.exit(f"Compilation failed: {exc}")

    ### Stitch 
    output_path = args.target / args.output
    log.info("Stitching %d PDF(s) → %s ...", len(pdf_files), output_path.name)
    try:
        stitch(pdf_files, output_path)
    except CompilerError as exc:
        sys.exit(f"PDF merge failed: {exc}")

    if not args.keep_tex:
        cleanup_chunk_pdfs(pdf_files)

    log.info("Done. Final PDF: %s", output_path)


### Entry point 

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    # --create-config is a standalone command that doesn't need SOURCE/TARGET
    if args.create_config is not None:
        from config import write_default_config
        try:
            write_default_config(Path(args.create_config))
        except FileExistsError as exc:
            sys.exit(str(exc))
        return

    run(args)


if __name__ == '__main__':
    main()