from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def data_dir() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def _fresh_levels():
    """Уровни событий запоминаются на часы (api.levels) — между тестами память не переносим."""
    from api.levels import LEVELS

    LEVELS.clear()
    yield
    LEVELS.clear()
