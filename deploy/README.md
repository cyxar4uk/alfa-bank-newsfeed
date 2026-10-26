# Стенд

Адрес: https://alfanews.anyway-community.ru. ВМ VK Cloud, каталог `/opt/alfa-bank-newsfeed`, compose-проект
`alfa-bank-newsfeed`. Наружу порты не публикуются: на ВМ уже работает обратный прокси (Caddy соседнего проекта), веб
подключён к его сети под именем `alfanews-web` (сеть — переменная `PROXY_NETWORK`). Нужен Compose 2.24+ (`!reset`),
на ВМ — 2.40.

Зарубежные реестры с ВМ открываются нестабильно, поэтому образы собираются локально и переносятся архивом.

## Обновить

Локально, в корне репо, на актуальном `main` (архив берётся из закоммиченного `HEAD`, не из рабочего дерева):

```bash
git pull
docker compose -f compose.yaml -f deploy/compose.server.yaml build api ingest web
docker pull postgres:17-alpine
docker save alfa-bank-newsfeed-api alfa-bank-newsfeed-ingest alfa-bank-newsfeed-web postgres:17-alpine | gzip -1 > images.tgz
git archive --format=tar.gz -o repo.tgz HEAD compose.yaml deploy data
scp images.tgz repo.tgz <пользователь>@<ВМ>:/opt/alfa-bank-newsfeed/upload/
```

На ВМ:

```bash
cd /opt/alfa-bank-newsfeed
tar -xzf upload/repo.tgz
gunzip -c upload/images.tgz | docker load
docker compose -f compose.yaml -f deploy/compose.server.yaml up -d --no-build
rm upload/*.tgz && docker image prune -f
```

`.env` на ВМ создаётся один раз по `.env.example`, права `600`: свой `POSTGRES_PASSWORD`, `LLM_API_KEY`, а в
`LLM_BASE_URL` — значение `LLM_BASE_URL_RU` (основной адрес моделей с ВМ не отвечает).

## Прогрев после выкатки

Отдельной команды нет: после `up -d` API само прогревает демо-пользователей.
- Ленты за день и неделю и карта рисков — сразу после старта и затем раз в 12 минут (`FEED_WARMUP`).
- Разборы событий — та же очередь, что разбор заранее (`PRECOMPUTE_*` в `.env`). Первый цикл идёт сразу после
  старта: карточки «важно» по убыванию значимости, не больше `PRECOMPUTE_IN_FLIGHT` одновременно и
  `PRECOMPUTE_PER_HOUR` в час. Уже собранные (та же версия агента) пропускаются. Бюджет — `PRECOMPUTE_BUDGET_RUB`
  в сутки.

Проверить через 10–15 минут:

```bash
curl -s https://alfanews.anyway-community.ru/api/precompute/status
```

В ответе: `built` — собрано заранее, `cache_hits` — уже было готово, `queued` — в очереди, `spent_rub` из
`budget_rub`, `stopped` — почему не ставит новые. В ленте у события `insight_state`: `ready` — откроется сразу,
`queued` — собирается.

Ручной прогрев с выбором пользователей и своим лимитом остаётся: `docker compose exec api python -m
api.agent.warmup --top 5`.

## Сертификат и прокси

Let's Encrypt не может проверить сервер по HTTP, поэтому сертификат выпускается через DNS-запись:

```bash
sudo certbot certonly --manual --preferred-challenges dns -d alfanews.anyway-community.ru
```

TXT-запись `_acme-challenge.alfanews` ставится у регистратора домена; файлы ложатся в
`/etc/letsencrypt/live/alfanews.anyway-community.ru/`. Сертификат действует 90 дней, продление — той же командой.

В Caddyfile соседнего проекта — блок домена с этим сертификатом и `reverse_proxy alfanews-web:80`; после правки
`caddy validate`, затем `caddy reload` (без перезапуска контейнера).
