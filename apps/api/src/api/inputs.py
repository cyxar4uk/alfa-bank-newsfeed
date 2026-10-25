"""«Мои числа» пользователя: долг, тип ставки, валютные закупки и закупка топлива в месяц — чтобы разбор
считал последствия в рублях его компании, а не «на каждый 1 млрд ₽». Хранятся по пользователю
(таблица user_inputs), агент берёт их через `user_inputs(persona_id)`."""

import datetime as dt
import json
from typing import Protocol

from psycopg_pool import ConnectionPool

from api.contract import UserInputs, UserInputsIn


class InputsStore(Protocol):
    def get(self, persona_id: str) -> UserInputs | None: ...

    def put(self, persona_id: str, data: UserInputsIn) -> UserInputs: ...


class MemoryInputs:
    def __init__(self) -> None:
        self._by_persona: dict[str, UserInputs] = {}

    def get(self, persona_id: str) -> UserInputs | None:
        return self._by_persona.get(persona_id)

    def put(self, persona_id: str, data: UserInputsIn) -> UserInputs:
        saved = UserInputs(**data.model_dump(), updated_at=dt.datetime.now(dt.UTC))
        self._by_persona[persona_id] = saved
        return saved


class PgInputs:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def get(self, persona_id: str) -> UserInputs | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT data, updated_at FROM user_inputs WHERE persona_id = %s", (persona_id,)
            ).fetchone()
        return UserInputs(**row[0], updated_at=row[1]) if row else None

    def put(self, persona_id: str, data: UserInputsIn) -> UserInputs:
        with self.pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO user_inputs (persona_id, data) VALUES (%s, %s::jsonb)"
                " ON CONFLICT (persona_id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()"
                " RETURNING updated_at",
                (persona_id, json.dumps(data.model_dump())),
            ).fetchone()
        return UserInputs(**data.model_dump(), updated_at=row[0])


STORE: InputsStore = MemoryInputs()  # api.main подменяет на PgInputs при старте


def user_inputs(persona_id: str) -> UserInputs | None:
    """«Мои числа» пользователя для расчёта разбора; не вводил — None."""
    try:
        return STORE.get(persona_id)
    except Exception:  # база недоступна — разбор считается без вводных, как раньше
        return None
