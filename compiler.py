"""
Compiles .tex chunks with lualatex and stitches them into one PDF.

Precondition: the caller (cli.py) has already verified that lualatex and
pdfunite are available on PATH before any processing begins. The checks
here are lightweight last-resort guards, not user-facing error handlers.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from tqdm import tqdm

logger = logging.getLogger(__name__)


class CompilerError(Exception):
    """Raised when lualatex or pdfunite fails or is not available."""


###  Binary availability 

def require_binary(name: str) -> str:
    """
    Return the full path to a required binary, or raise CompilerError.
    Used as a last-resort check inside compiler functions.
    """
    path = shutil.which(name)
    if not path:
        raise CompilerError(
            f"'{name}' not found on PATH. "
            f"This should have been caught at startup — please report this bug."
        )
    return path


###  lualatex 

def compile_chunk(tex_path: Path, runs: int = 1) -> Path:
    """
    Compile a single .tex file with lualatex.

    lualatex is run with -interaction=nonstopmode so it never pauses for input.
    Output goes to the same directory as the .tex file.

    Args:
        tex_path: path to the .tex file.
        runs:     number of lualatex passes (1 is sufficient for chat logs
                  since there are no cross-references or TOC entries).

    Returns:
        Path to the produced .pdf file.

    Raises:
        CompilerError: if lualatex is missing or exits with a non-zero code.
        FileNotFoundError: if tex_path does not exist.
    """
    if not tex_path.exists():
        raise FileNotFoundError(f"Source file not found: {tex_path}")

    lualatex = require_binary('lualatex')

    cmd = [
        lualatex,
        '-interaction=nonstopmode',
        '-halt-on-error',
        f'-output-directory={tex_path.parent}',
        str(tex_path),
    ]

    for run in range(runs):
        logger.debug("lualatex pass %d/%d: %s", run + 1, runs, tex_path.name)
        result = subprocess.run(
            cmd,
            cwd=tex_path.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            # Write the lualatex log to a .err file for post-mortem inspection.
            err_path = tex_path.with_suffix('.err')
            err_path.write_bytes(result.stdout)
            raise CompilerError(
                f"lualatex failed on {tex_path.name} (exit {result.returncode}). "
                f"See {err_path} for the full log."
            )

    pdf_path = tex_path.with_suffix('.pdf')
    if not pdf_path.exists():
        raise CompilerError(
            f"lualatex reported success but {pdf_path.name} was not produced."
        )

    logger.debug("Produced %s", pdf_path.name)
    return pdf_path


def compile_all(tex_files: list[Path], keep_tex: bool = False) -> list[Path]:
    """
    Compile every .tex file in the list, with a tqdm progress bar.

    Args:
        tex_files:  ordered list of .tex chunk paths.
        keep_tex:   if False, delete .tex and lualatex auxiliary files
                    (.aux, .log, .out) after successful compilation.

    Returns:
        Ordered list of produced .pdf paths.

    Raises:
        CompilerError: on the first chunk that fails (remaining chunks
                       are not attempted).
    """
    pdf_files: list[Path] = []

    for tex_path in tqdm(tex_files, desc='Compiling chunks', unit='chunk'):
        pdf_path = compile_chunk(tex_path)
        pdf_files.append(pdf_path)

        if not keep_tex:
            _remove_aux_files(tex_path)

    return pdf_files


def _remove_aux_files(tex_path: Path) -> None:
    """Delete lualatex auxiliary files and optionally the .tex source."""
    for suffix in ('.tex', '.aux', '.log', '.out'):
        candidate = tex_path.with_suffix(suffix)
        if candidate.exists():
            try:
                candidate.unlink()
            except OSError as exc:
                logger.warning("Could not remove %s: %s", candidate, exc)


###  pdfunite 

def stitch(pdf_files: list[Path], output_path: Path) -> Path:
    """
    Merge an ordered list of PDF files into a single PDF using pdfunite.

    Args:
        pdf_files:   ordered list of per-chunk .pdf paths.
        output_path: destination path for the final merged PDF.

    Returns:
        output_path after successful merge.

    Raises:
        CompilerError: if pdfunite is missing or exits with a non-zero code.
        ValueError: if pdf_files is empty.
    """
    if not pdf_files:
        raise ValueError("No PDF files to stitch.")

    if len(pdf_files) == 1:
        # Nothing to merge — just move/copy the single file.
        shutil.copy2(pdf_files[0], output_path)
        logger.debug("Single chunk — copied to %s", output_path)
        return output_path

    pdfunite = require_binary('pdfunite')

    cmd = [pdfunite] + [str(p) for p in pdf_files] + [str(output_path)]

    logger.debug("Stitching %d PDFs → %s", len(pdf_files), output_path.name)
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    if result.returncode != 0:
        raise CompilerError(
            f"pdfunite failed (exit {result.returncode}): "
            f"{result.stdout.decode(errors='replace').strip()}"
        )

    if not output_path.exists():
        raise CompilerError(
            f"pdfunite reported success but {output_path} was not produced."
        )

    logger.info("Final PDF: %s", output_path)
    return output_path


def cleanup_chunk_pdfs(pdf_files: list[Path]) -> None:
    """Delete per-chunk PDF files after successful stitching."""
    for p in pdf_files:
        if p.exists():
            try:
                p.unlink()
            except OSError as exc:
                logger.warning("Could not remove %s: %s", p, exc)