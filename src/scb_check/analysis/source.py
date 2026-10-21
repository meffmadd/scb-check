"""Read source text and apply parser dispatch with warn-and-skip failures."""

from __future__ import annotations

from pathlib import Path

from scb_check.logging import get_logger
from scb_check.tree_walking.dispatch import ParsedFile
from scb_check.tree_walking.dispatch import ProjectParseError
from scb_check.tree_walking.dispatch import parse_source_file


def read_and_parse_source(file_path: Path) -> ParsedFile | None:
    """Read and parse `file_path`, warning and returning `None` on failure."""
    try:
        try:
            source = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            get_logger(__name__).warning(
                "file is not valid UTF-8, reading with replacement characters",
                file=str(file_path),
            )
            source = file_path.read_text(encoding="utf-8", errors="replace")
        return parse_source_file(file_path, source)
    except (OSError, ProjectParseError) as exc:
        get_logger(__name__).warning(
            "failed to parse file",
            file=str(file_path),
            error=str(exc),
        )
        return None
