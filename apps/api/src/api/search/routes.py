"""API материалов для фронта: лента новостей с разметкой и первоисточник для перехода из карточки."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.search.models import AlfaFragment, NewsItem, NewsPage
from api.search.repo import SearchRepo, UnknownFilter

router = APIRouter(prefix="/api", tags=["материалы"])


def get_search(request: Request) -> SearchRepo:
    return request.app.state.search


Search = Annotated[SearchRepo, Depends(get_search)]


@router.get("/news", response_model=NewsPage)
def list_news(
    search: Search,
    q: Annotated[str, Query(max_length=300, description="слова в любой форме: «ключевую ставку»")] = "",
    factor: Annotated[
        list[str] | None,
        Query(description="код или название фактора (rate, fx, «курс валют»), можно несколько"),
    ] = None,
    sector: Annotated[
        list[str] | None, Query(description="двузначный ОКВЭД, код компании (45.31.1) или название отрасли")
    ] = None,
    since: Annotated[dt.datetime | None, Query(description="не раньше, ISO 8601; без пояса — МСК")] = None,
    min_strength: Annotated[
        float, Query(ge=0, le=1, description="минимальная сила связи с фактором (без factor — с любым)")
    ] = 0.0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> NewsPage:
    """Лента материалов с разметкой: свежие первыми, с запросом `q` — лучшие совпадения первыми."""
    try:
        return search.list_news(q, factor, sector, since, limit, offset, min_strength)
    except UnknownFilter as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sources/{source_id:path}", response_model=NewsItem | AlfaFragment)
def get_source(source_id: str, search: Search) -> NewsItem | AlfaFragment:
    """Первоисточник по id из `refs`: новость (`src:news:…`) или аналитика банка
    (`src:alfa:<материал>#p<N>-<n>`, страница `#p<N>`, материал целиком). Знак `#` в пути — `%23`."""
    source = search.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="источник не найден")
    return source  # у фрагмента аналитики fragment уже не длиннее 600 знаков (AlfaFragment)
