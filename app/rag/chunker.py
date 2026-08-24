"""Heading-aware Markdown chunking."""

from dataclasses import dataclass
import re
from typing import Any

from .loader import Document


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    source_filename: str
    heading: str
    metadata: dict[str, Any]


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def chunk_document(document: Document, max_chars: int = 1200) -> list[Chunk]:
    """Split sections while repeating the heading context on every chunk."""
    sections: list[tuple[str, list[str]]] = []
    heading_stack: list[str] = []
    current_lines: list[str] = []

    def flush() -> None:
        if current_lines and "\n".join(current_lines).strip():
            sections.append((" > ".join(heading_stack), current_lines.copy()))

    for line in document.body.splitlines():
        match = HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            heading_stack[:] = heading_stack[: level - 1]
            heading_stack.append(match.group(2))
            current_lines.clear()
        else:
            current_lines.append(line)
    flush()

    chunks: list[Chunk] = []
    for section_index, (heading, lines) in enumerate(sections):
        content = "\n".join(lines).strip()
        prefix = f"Source: {document.source_filename}\nHeading: {heading}\n\n"
        available = max(1, max_chars - len(prefix))
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
        pieces: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if current and len(current) + len(paragraph) + 2 > available:
                pieces.append(current)
                current = ""
            if len(paragraph) > available:
                if current:
                    pieces.append(current)
                    current = ""
                pieces.extend(
                    paragraph[index : index + available]
                    for index in range(0, len(paragraph), available)
                )
            else:
                current = paragraph if not current else f"{current}\n\n{paragraph}"
        if current:
            pieces.append(current)

        for piece_index, piece in enumerate(pieces):
            chunks.append(
                Chunk(
                    chunk_id=f"{document.source_filename}:{section_index}:{piece_index}",
                    text=f"{prefix}{piece}",
                    source_filename=document.source_filename,
                    heading=heading or "Document",
                    metadata=dict(document.metadata),
                )
            )
    return chunks