"""Распознавание страницы в абзацы. Движок сменный: Tesseract сейчас, Qwen3-VL — когда будет ключ."""

import base64
import csv
import io
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image


@dataclass
class OcrBlock:
    """Абзац на странице: текст, средняя уверенность распознавания 0–100, рамка в пикселях (x, y, w, h)."""

    text: str
    confidence: float
    bbox: tuple[int, int, int, int]

    def to_dict(self) -> dict:
        return asdict(self)


class OcrEngine(Protocol):
    name: str

    def recognize(self, image: Image.Image) -> list[OcrBlock]: ...


class OcrUnavailable(RuntimeError):
    pass


class TesseractEngine:
    """Tesseract 5 через командную строку, языки rus+eng, вывод TSV с разметкой блоков и абзацев."""

    name = "tesseract"

    def __init__(self, langs: str = "rus+eng", psm: int = 3, binary: str = "tesseract"):
        self.langs = langs
        self.psm = psm
        self.binary = shutil.which(binary)
        if self.binary is None:
            raise OcrUnavailable(
                "tesseract не найден. Docker-образ ставит его сам; локально: "
                "apt install tesseract-ocr tesseract-ocr-rus · brew install tesseract tesseract-lang · "
                "Windows — сборка UB Mannheim (github.com/UB-Mannheim/tesseract/wiki) с языком rus"
            )

    def version(self) -> str:
        out = subprocess.run([self.binary, "--version"], capture_output=True, text=True, check=True)
        return (out.stdout or out.stderr).splitlines()[0]

    def recognize(self, image: Image.Image) -> list[OcrBlock]:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        try:
            proc = subprocess.run(
                [self.binary, "stdin", "stdout", "-l", self.langs, "--psm", str(self.psm), "tsv"],
                input=buf.getvalue(),
                capture_output=True,
                check=True,
                # страницы распознаются параллельно, внутренние потоки tesseract только мешают
                env={**os.environ, "OMP_THREAD_LIMIT": "1"},
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            # чаще всего не установлен язык rus — подсказка есть в stderr tesseract
            detail = getattr(exc, "stderr", b"") or b""
            raise OcrUnavailable(
                f"tesseract не смог распознать страницу: {detail.decode('utf-8', 'replace')[:200]}"
            ) from exc
        return blocks_from_tsv(proc.stdout.decode("utf-8"))


@dataclass
class _Word:
    text: str
    conf: float
    line: int
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width


# минимальная ширина пустой вертикальной полосы между колонками — в высотах строки, по числу строк в абзаце:
# чем меньше строк, тем шире должен быть промежуток, чтобы не принять растянутые пробелы за границу колонок
_GUTTER_HEIGHTS = {1: 2.5, 2: 1.5}
_GUTTER_HEIGHTS_MANY = 0.8


def blocks_from_tsv(tsv: str) -> list[OcrBlock]:
    """Слова TSV → абзацы (block_num, par_num); строки внутри абзаца склеиваются с учётом переносов.

    На слайдах Tesseract часто кладёт в один абзац строки текста и стоящего рядом графика. Такой абзац режем
    по вертикальным полосам, свободным от слов во всех строках: текст и подписи графика становятся разными блоками.
    """
    paragraphs: dict[tuple[int, int], list[_Word]] = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row.get("level") != "5" or not (row.get("text") or "").strip():
            continue
        key = (int(row["block_num"]), int(row["par_num"]))
        paragraphs.setdefault(key, []).append(
            _Word(
                text=row["text"].strip(),
                conf=float(row["conf"]),
                line=int(row["line_num"]),
                left=int(row["left"]),
                top=int(row["top"]),
                width=int(row["width"]),
                height=int(row["height"]),
            )
        )
    blocks = []
    for words in paragraphs.values():
        for column in _split_columns(words):
            blocks.append(_to_block(column))
    return blocks


def _split_columns(words: list[_Word]) -> list[list[_Word]]:
    lines = {w.line for w in words}
    heights = sorted(w.height for w in words)
    min_gutter = heights[len(heights) // 2] * _GUTTER_HEIGHTS.get(len(lines), _GUTTER_HEIGHTS_MANY)
    x0 = min(w.left for w in words)
    covered = [False] * (max(w.right for w in words) - x0)
    for w in words:
        covered[w.left - x0 : w.right - x0] = [True] * w.width

    cuts, run_start = [], None
    for x, busy in enumerate(covered):
        if not busy and run_start is None:
            run_start = x
        elif busy and run_start is not None:
            if x - run_start >= min_gutter:
                cuts.append(x0 + (run_start + x) // 2)
            run_start = None
    if not cuts:
        return [words]
    columns: list[list[_Word]] = [[] for _ in range(len(cuts) + 1)]
    for w in words:
        center = w.left + w.width // 2
        columns[sum(center > c for c in cuts)].append(w)
    return [c for c in columns if c]


def _to_block(words: list[_Word]) -> OcrBlock:
    lines: dict[int, list[_Word]] = {}
    for w in words:
        lines.setdefault(w.line, []).append(w)
    text = join_lines([" ".join(w.text for w in sorted(ws, key=lambda w: w.left)) for _, ws in sorted(lines.items())])
    confs = [w.conf for w in words if w.conf >= 0]
    left = min(w.left for w in words)
    top = min(w.top for w in words)
    right = max(w.right for w in words)
    bottom = max(w.top + w.height for w in words)
    return OcrBlock(
        text=text,
        confidence=round(sum(confs) / len(confs), 1) if confs else 0.0,
        bbox=(left, top, right - left, bottom - top),
    )


_HYPHEN_END = re.compile(r"[a-zа-яё]-$", re.I)


def join_lines(lines: list[str]) -> str:
    """«ввод-» + «имых» → «вводимых»; дефис перед заглавной или цифрой сохраняем («Санкт-» + «Петербург»)."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if _HYPHEN_END.search(out):
            out = out[:-1] + line if line[0].islower() else out + line
        elif out:
            out += " " + line
        else:
            out = line
    return out


class VisionClient(Protocol):
    """Клиент мультимодальной модели: картинка + инструкция → текст."""

    model: str

    def complete(self, image_png: bytes, prompt: str) -> str: ...


VLM_PROMPT = (
    "Это скан страницы аналитического отчёта на русском языке. Перепиши весь текст страницы дословно, ничего не "
    "пересказывая и не добавляя от себя. Сохраняй порядок чтения: колонки и блоки слайда — по очереди. Абзацы раздели "
    "пустой строкой. Таблицу выведи отдельным абзацем: каждая строка таблицы — на своей строке, ячейки через « | », "
    "числа ровно как на странице. Подписи осей и легенды графиков пропускай, название графика и источник оставляй. "
    "Ответ — только текст страницы, без пояснений и без разметки Markdown."
)
VLM_MAX_SIDE = 2000


# модель иногда зацикливается и повторяет фразу до лимита токенов — оставляем одно повторение
_LOOP = re.compile(r"(.{15,300}?)\1{3,}", re.S)


def cut_loops(text: str) -> str:
    return _LOOP.sub(r"\1", text)


def _paragraph(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # строки таблицы склеивать нельзя — каждая строка остаётся строкой
    if sum(" | " in line for line in lines) >= 2:
        return "\n".join(lines)
    return join_lines(lines)


class VisionLlmEngine:
    """Распознавание мультимодальной моделью (Qwen3-VL-30B-A3B-Instruct). Уверенности у модели нет — ставим 100."""

    # запросов к API одновременно: больше — упираемся в лимиты шлюза
    workers = 6

    def __init__(self, client: VisionClient, max_side: int = VLM_MAX_SIDE, name: str = "qwen3-vl"):
        self.client = client
        self.max_side = max_side
        # заглушка называется иначе, чтобы её пустые страницы не попали в кэш настоящей модели
        self.name = name

    def recognize(self, image: Image.Image) -> list[OcrBlock]:
        if max(image.size) > self.max_side:
            scale = self.max_side / max(image.size)
            image = image.resize((round(image.size[0] * scale), round(image.size[1] * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        from ingest.llm import LlmUnavailable

        try:
            text = cut_loops(self.client.complete(buf.getvalue(), VLM_PROMPT))
        except LlmUnavailable as exc:
            raise OcrUnavailable(str(exc)) from exc
        w, h = image.size
        return [
            OcrBlock(text=_paragraph(par), confidence=100.0, bbox=(0, 0, w, h))
            for par in re.split(r"\n\s*\n", text)
            if par.strip()
        ]


class ApiVisionClient:
    """Мультимодальная модель через API организаторов: картинка уходит data-URL в сообщении."""

    def __init__(self, llm, model: str = "qwen/qwen3-vl-30b-a3b-instruct", max_tokens: int = 4000):
        self.llm = llm
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, image_png: bytes, prompt: str) -> str:
        url = "data:image/png;base64," + base64.b64encode(image_png).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": url}}, {"type": "text", "text": prompt}],
            }
        ]
        return self.llm.chat(self.model, messages, purpose="ocr", max_tokens=self.max_tokens).text


class MockVisionClient:
    """Заглушка до появления ключа: возвращает заданный текст, сеть не трогает."""

    model = "Qwen3-VL-30B-A3B-Instruct (заглушка)"

    def __init__(self, text: str = ""):
        self.text = text

    def complete(self, image_png: bytes, prompt: str) -> str:
        return self.text


class CacheOnlyEngine:
    """Движка нет на машине: страницы берутся только из кэша, нераспознанная страница — ошибка с подсказкой."""

    cache_only = True

    def __init__(self, name: str, reason: str):
        self.name = name
        self.reason = reason

    def recognize(self, image: Image.Image) -> list[OcrBlock]:
        raise OcrUnavailable(self.reason)


def make_engine(name: str, journal: Path | None = None) -> OcrEngine:
    if name == "tesseract":
        return TesseractEngine()
    if name == "qwen3-vl-mock":
        return VisionLlmEngine(MockVisionClient(), name="qwen3-vl-mock")
    if name == "qwen3-vl":
        from ingest.llm import LlmClient, LlmUnavailable

        try:
            llm = LlmClient.from_env(journal)
        except LlmUnavailable as exc:
            raise OcrUnavailable(str(exc)) from exc
        return VisionLlmEngine(ApiVisionClient(llm))
    raise ValueError(f"неизвестный движок распознавания: {name}")
