"""Splits page texts into retrieval chunks that always remember their page.

Page first, then paragraph: paragraphs are packed into chunks of up to `size` characters. A paragraph
longer than `size` is cut into word-boundary windows that overlap by about `overlap` characters, so an
answer that straddles a cut is still found. A chunk never spans two pages, so every citation [p.N] maps
to exactly one page.
"""

import re
from dataclasses import dataclass

_PARA_SPLIT = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class Chunk:
    page: int
    index: int
    text: str


def _windows(text: str, size: int, overlap: int) -> list[str]:
    """Cut one long paragraph into overlapping windows without breaking words."""
    words = text.split()
    out: list[str] = []
    start = 0
    while start < len(words):
        length, end = 0, start
        while end < len(words) and length + len(words[end]) + (1 if end > start else 0) <= size:
            length += len(words[end]) + (1 if end > start else 0)
            end += 1
        if end == start:  # a single word longer than size: hard-cut it
            out.append(words[start][:size])
            start += 1
            continue
        out.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        # Step back far enough to repeat ~overlap characters, but always move forward.
        back, back_len = end, 0
        while back > start + 1 and back_len + len(words[back - 1]) + 1 <= overlap:
            back -= 1
            back_len += len(words[back]) + 1
        start = back
    return out


def _page_chunks(text: str, size: int, overlap: int) -> list[str]:
    paras = [p.strip() for p in _PARA_SPLIT.split(text) if p.strip()]
    out: list[str] = []
    current = ""
    for p in paras:
        if len(p) > size:
            if current:
                out.append(current)
                current = ""
            out.extend(_windows(p, size, overlap))
        elif not current:
            current = p
        elif len(current) + 2 + len(p) <= size:
            current = f"{current}\n\n{p}"
        else:
            out.append(current)
            current = p
    if current:
        out.append(current)
    return out


def chunk_pages(pages: list[tuple[int, str]], size: int = 800, overlap: int = 150) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page, text in pages:
        for piece in _page_chunks(text, size, overlap):
            chunks.append(Chunk(page=page, index=len(chunks), text=piece))
    return chunks
