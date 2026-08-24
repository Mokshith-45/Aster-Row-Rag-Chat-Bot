"""Load Markdown files while preserving their front matter and source identity."""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Document:
    source_filename: str
    body: str
    metadata: dict[str, Any]


def parse_markdown_document(path: Path) -> Document:
    """Parse one Markdown document with YAML front matter."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"Missing YAML front matter: {path.name}")

    lines = text.splitlines()
    try:
        end_index = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError(f"Unterminated YAML front matter: {path.name}") from exc

    raw_metadata = yaml.safe_load("\n".join(lines[1:end_index])) or {}
    if not isinstance(raw_metadata, dict):
        raise ValueError(f"Front matter must be a mapping: {path.name}")

    metadata = {
        str(key): value.isoformat() if isinstance(value, (date, datetime)) else value
        for key, value in raw_metadata.items()
    }
    return Document(
        source_filename=path.name,
        body="\n".join(lines[end_index + 1 :]).strip(),
        metadata=metadata,
    )


def load_documents(knowledge_base_dir: Path) -> list[Document]:
    """Load every Markdown source in deterministic filename order."""
    return [
        parse_markdown_document(path)
        for path in sorted(knowledge_base_dir.glob("*.md"))
    ]