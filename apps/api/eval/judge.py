"""Судья замера: разрешённая модель организаторов, ответ в JSON, кэш на диске и свой лимит расходов.

Судья — Qwen3.6 35B A3B. В этом прогоне сервис её не вызывал (разборы шли на Gemma и DeepSeek), поэтому судья
не оценивает свои же ответы. Кэш лежит в `eval/cache/judge/` локально (в git не попадает): повторный прогон с тем же набором
бесплатный и даёт ту же разметку. Ключ берётся из окружения или из .env и никуда не пишется.
"""

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

JUDGE_MODEL = "qwen/qwen3.6-35b-a3b"
HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "cache" / "judge"


class JudgeBudgetExceeded(RuntimeError):
    pass


def read_env(path: Path | None) -> dict[str, str]:
    """LLM_API_KEY и LLM_BASE_URL: из окружения, иначе из файла .env."""
    env = {k: os.environ[k] for k in ("LLM_API_KEY", "LLM_BASE_URL") if os.environ.get(k)}
    if path and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip().strip('"'))
    return env


class Judge:
    def __init__(self, env: dict[str, str], budget_rub: float, offline: bool = False) -> None:
        self.key = env.get("LLM_API_KEY", "")
        self.base = env.get("LLM_BASE_URL", "").rstrip("/")
        self.budget = budget_rub
        self.offline = offline
        self.spent = 0.0
        self.calls = 0
        self.cached = 0

    def ask(self, system: str, user: str) -> dict:
        body = {
            "model": JUDGE_MODEL,
            "temperature": 0,
            "max_tokens": 3000,
            "reasoning": {"enabled": False},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        path = CACHE_DIR / digest[:2] / f"{digest}.json"
        if path.exists():
            self.cached += 1
            return json.loads(path.read_text(encoding="utf-8"))["answer"]
        if self.offline:
            raise RuntimeError("ответа судьи нет в кэше, а прогон без моделей (--offline)")
        if not self.key or not self.base:
            raise RuntimeError("нет LLM_API_KEY или LLM_BASE_URL — судье не к кому обратиться")
        if self.spent >= self.budget:
            raise JudgeBudgetExceeded(f"судья потратил {self.spent:.2f} ₽ из {self.budget:.2f} ₽")
        answer, cost = self._post(body)
        self.spent += cost
        self.calls += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"model": JUDGE_MODEL, "cost": cost, "answer": answer}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        return answer

    def _post(self, body: dict) -> tuple[dict, float]:
        data = json.dumps(body, ensure_ascii=False).encode()
        last = ""
        for attempt in range(4):
            req = urllib.request.Request(
                self.base + "/chat/completions",
                data=data,
                headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    payload = json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                last = f"судья ответил {exc.code}"
                if exc.code in (408, 429, 500, 502, 503, 504):
                    time.sleep(2 * 2**attempt)
                    continue
                raise RuntimeError(last) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last = f"нет ответа судьи: {exc}"
                time.sleep(2 * 2**attempt)
                continue
            cost = float((payload.get("usage") or {}).get("cost") or 0.0)
            text = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            try:
                return parse_json(text), cost
            except ValueError:
                self.spent += cost
                last = "судья вернул не JSON"
                continue
        raise RuntimeError(last)


def parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("нет JSON")
    return json.loads(text[start : end + 1])
