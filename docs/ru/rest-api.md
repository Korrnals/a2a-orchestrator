# REST API

REST-обёртка на FastAPI зеркалирует MCP-инструменты поверх HTTP, чтобы
не-VS Code рантаймы (CLI, web-приложения, внешние сервисы) могли
использовать оркестратор.

## Свойства сервера

| Свойство | Значение |
| --- | --- |
| Порт по умолчанию | `8789` |
| Зависимости | `pip install -e ".[web]"` (fastapi + uvicorn) |
| CORS | `A2A_WEB_CORS_ORIGINS` (через запятую) |
| Auth | `A2A_WEB_API_KEY` (заголовок `X-API-Key`; нет = без auth) |

## Эндпоинты

| Метод | Путь | Соответствует |
| --- | --- | --- |
| `GET` | `/health` | Проверка здоровья |
| `POST` | `/v1/send` | `send_a2a` |
| `GET` | `/v1/context/{session_id}/{turn_id}` | `load_context` |
| `GET` | `/v1/chain/{session_id}` | `get_chain_status` |
| `GET` | `/v1/metrics` | `get_metrics` |
| `GET` | `/v1/saga/{saga_id}` | `get_saga_status` |
| `POST` | `/v1/search` | `search_messages` |
| `GET` | `/v1/agents` | Список зарегистрированных агентов |
| `POST` | `/v1/register/challenge` | `create_registration_challenge` |
| `POST` | `/v1/register` | `register_agent` |
| `DELETE` | `/v1/register/{agent_id}` | `unregister_agent` |
| `GET` | `/v1/tenants` | `list_tenants` |

## Запуск web-сервера

```bash
# Только web-сервер
a2a-cli web --host 127.0.0.1 --port 8789

# Или вместе с MCP + WS
a2a-cli serve --all
```

## Примеры

### Отправка через REST

```bash
curl -X POST http://127.0.0.1:8789/v1/send \
  -H "Content-Type: application/json" \
  -d '{
    "target": "agent-dba",
    "from_id": "agent-tech-lead",
    "reason": "Task requires database expertise",
    "summary": "User needs a migration for the orders table"
  }'
```

### С API-ключом

```bash
curl -X POST http://127.0.0.1:8789/v1/send \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $A2A_WEB_API_KEY" \
  -d '{"target": "agent-dba", "from_id": "agent-a", "reason": "...", "summary": "..."}'
```

### Поиск сообщений

```bash
curl -X POST http://127.0.0.1:8789/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "orders migration", "limit": 5}'
```

### Проверка здоровья

```bash
curl http://127.0.0.1:8789/health
# → {"status": "ok"}
```

## См. также

- [Конфигурация](configuration.md) — переменные `A2A_WEB_*`
- [Справочник CLI](cli-reference.md) — команды `web` и `serve --all`
- [Справочник инструментов](tools-reference.md) — эквиваленты MCP-инструментов