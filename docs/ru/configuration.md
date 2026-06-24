# Конфигурация

Все настройки — переменные окружения. Имена `A2A_*` основные; старые
имена `GCW_*` принимаются как backward-compat fallback.

## Переменные окружения

| Переменная | Legacy-fallback | По умолчанию | Назначение |
| --- | --- | --- | --- |
| `A2A_CARDS_DIR` | `GCW_CARDS_DIR` | автоопределение | Каталог с JSON-файлами Agent Card (`a2a/agents/*.json`) |
| `A2A_SCHEMA_DIR` | `GCW_SCHEMA_DIR` | встроенные | Каталог с `agent-card.schema.json` и `a2a-message.schema.json` |
| `A2A_FALLBACK_JSONL` | `GCW_A2A_FALLBACK_JSONL` | `~/.a2a/a2a-messages.jsonl` | Путь к JSONL-файлу fallback |
| `MNEMOS_BASE_URL` | — | `http://127.0.0.1:8787` | Базовый URL REST API Mnemos |
| `A2A_ORCHESTRATOR_LOG_LEVEL` | `GCW_ORCHESTRATOR_LOG_LEVEL` | `INFO` | Уровень логирования (`DEBUG`, `INFO`, `WARNING`, …) |
| `A2A_WS_PORT` | — | `8788` | Порт WebSocket-сервера |
| `A2A_WEB_CORS_ORIGINS` | — | `http://localhost,http://127.0.0.1` | CORS-origins для web-сервера (через запятую) |
| `A2A_WEB_API_KEY` | — | *(нет = без auth)* | API-ключ для web-сервера (заголовок `X-API-Key`) |

## Автоопределение

### `A2A_CARDS_DIR`

1. Сама переменная окружения, если задана.
2. `a2a/agents` под любым родителем каталога пакета (in-tree dev).

В продакшене всегда задавайте `A2A_CARDS_DIR` явно — не полагайтесь на
автоопределение.

### `A2A_SCHEMA_DIR`

1. Сама переменная окружения, если задана.
2. Встроенные схемы в `a2a_orchestrator/schemas/` (по умолчанию —
   внешний каталог не нужен).
3. `docs/a2a/schemas/` под любым родителем каталога пакета (последнее
   средство для in-tree dev-чек аутов).

## Настройка `mcp.json` в VS Code

```json
{
  "servers": {
    "a2a-orchestrator": {
      "command": "python3",
      "args": ["-m", "a2a_orchestrator"],
      "env": {
        "A2A_CARDS_DIR": "/path/to/agent/cards",
        "MNEMOS_BASE_URL": "http://127.0.0.1:8787"
      }
    }
  }
}
```

После правки перезагрузите окно
(**Ctrl+Shift+P → Developer: Reload Window**), чтобы MCP-хост
перечитал конфигурацию.

> **Примечание для distrobox / sandbox.** Если используете `envFile`,
> всегда указывайте **абсолютный** путь — `~/` разрешается против
> root-namespace MCP-хоста, а не пользовательского `$HOME`.

## Минимальная конфигурация (без Mnemos)

Оркестратор работает без Mnemos — сообщения падают в локальный
JSONL-файл. Этого достаточно для однодеревной машины:

```bash
export A2A_CARDS_DIR=/path/to/agent/cards
python3 -m a2a_orchestrator
```

## Полная конфигурация (с web-сервером)

```bash
export A2A_CARDS_DIR=/path/to/agent/cards
export MNEMOS_BASE_URL=http://127.0.0.1:8787
export A2A_WS_PORT=8788
export A2A_WEB_CORS_ORIGINS=https://my-app.example.com
export A2A_WEB_API_KEY=secret-key-here
a2a-orchestrator serve --all
```

## См. также

- [Начало работы](getting-started.md) — первые шаги
- [REST API](rest-api.md) — эндпоинты web-сервера
- [WebSocket](websockets.md) — настройка WS-сервера