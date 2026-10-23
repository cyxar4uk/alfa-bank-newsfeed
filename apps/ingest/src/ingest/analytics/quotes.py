"""Сверка цитаты банка с распознанным текстом страницы (фича F: ни одна цитата не выдумана).

Сравниваем с точностью до пробелов и переносов строк: распознанный текст и цитата могут по-разному разбить строки.
Буквы, цифры и знаки должны совпасть — пересказ не пройдёт.
"""

import re

from ingest.models import Source

_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def page_text_for(fragment: Source, page: Source) -> str:
    """Текст страницы того движка, которым распознан фрагмент."""
    if fragment.ocr_engine == "qwen3-vl":
        return page.vlm_text or ""
    return page.fragment


def quote_in_page(quote: str, page_text: str) -> bool:
    quote = normalize(quote)
    return bool(quote) and quote in normalize(page_text)
