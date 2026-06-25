# Справочник CLI

CLI `a2a-cli` оборачивает те же внутренние функции, что и
MCP-инструменты. Удобно для скриптинга, отладки и дымового тестирования
без MCP-клиента.

Использует `argparse` (без лишних зависимостей), поэтому CLI работает
в любом окружении Python 3.11+ без установки дополнительных пакетов.

## Команды

| Команда | Назначение |
| --- | --- |
| `send` | Отправить A2A-сообщение |
| `list` | Недавние сообщения сессии |
| `status` | Статус цепочки сессии |
| `agents` | Список зарегистрированных агентов |
| `metrics` | Счётчики метрик |
| `serve` | Запуск MCP-сервера (`--ws`, `--all`) |
| `web` | Запуск web/HTTP-сервера |
| `ws-monitor` | Мониторинг WebSocket-событий |
| `search` | Поиск A2A-сообщений |
| `saga` | Управление сагами (`list`, `status`) |
| `register` | Регистрация внешнего агента |
| `tenants` | Управление тенантами (`list`) |

## Примеры

### Отправить сообщение

```bash
a2a-cli send --from agent-a --to agent-b \
  --reason "Требуется экспертиза по базе данных" \
  --summary "Нужна миграция таблицы orders" \
  --session-id conv-001
```

### Недавние сообщения

```bash
a2a-cli list --session-id conv-001 --limit 10
```

### Статус цепочки

```bash
a2a-cli status --session-id conv-001
```

### Список зарегистрированных агентов

```bash
a2a-cli agents
```

### Счётчики метрик

```bash
a2a-cli metrics
```

### Запуск MCP-сервера

```bash
# То же что python3 -m a2a_orchestrator
a2a-cli serve

# MCP + WebSocket
a2a-cli serve --ws

# MCP + WebSocket + Web-сервер
a2a-cli serve --all --web-host 127.0.0.1 --web-port 8789
```

### Только web/HTTP-сервер

```bash
a2a-cli web --host 127.0.0.1 --port 8789
```

### Мониторинг WebSocket-событий

```bash
a2a-cli ws-monitor --session-id conv-001
```

### Поиск сообщений

```bash
a2a-cli search "orders migration" --limit 5
```

### Управление сагами

```bash
a2a-cli saga list --status active
a2a-cli saga status saga-abc123
```

### Регистрация внешнего агента

Двухшаговый поток: challenge, затем подпись + отправка.

```bash
# Шаг 1: получить challenge-nonce
a2a-cli register --agent-card card.json --public-key key.b64

# Шаг 2: подписать nonce и отправить
a2a-cli register --agent-card card.json --public-key key.b64 --signature <sig>
```

### Список тенантов

```bash
a2a-cli tenants list
```

## См. также

- [Справочник инструментов](tools-reference.md) — эквиваленты MCP-инструментов
- [Конфигурация](configuration.md) — переменные окружения
- [Внешние агенты](external-agents.md) — поток регистрации