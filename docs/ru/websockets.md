# WebSocket

Оркестратор может запускать WebSocket-сервер параллельно с MCP-сервером
stdio. Клиенты подписываются на события сессии и получают push-уведомления,
когда A2A-сообщения доставляются, отклоняются или состояние цепочки
меняется.

## Свойства сервера

| Свойство | Значение |
| --- | --- |
| Порт по умолчанию | `8788` (`A2A_WS_PORT`) |
| Протокол | `ws://` (без TLS в конфигурации по умолчанию) |
| Опционально | Если `websockets` не установлен, молча деградирует до no-push |

## Типы событий

| Событие | Когда |
| --- | --- |
| `a2a_delivered` | A2A-сообщение успешно маршрутизировано |
| `a2a_rejected` | A2A-сообщение отклонено (R1–R6) |
| `chain_updated` | Состояние цепочки/бюджета сессии изменилось |
| `saga_completed` | Сага помечена как завершённая |
| `saga_abandoned` | Сага покинута |

## Запуск с WebSocket

```bash
# MCP + WebSocket
a2a-orchestrator serve --ws

# MCP + WebSocket + Web-сервер
a2a-orchestrator serve --all

# Мониторинг событий сессии
a2a-orchestrator ws-monitor --session-id conv-abc
```

## Payload события

Каждое событие — JSON-объект, вещаемый всем подписанным клиентам:

```json
{
  "event": "a2a_delivered",
  "session_id": "conv-abc",
  "message_id": "msg-a1b2c3d4e5f6",
  "from": "agent-tech-lead",
  "to": "agent-dba",
  "timestamp": "2026-06-24T12:00:00Z"
}
```

Отклонённые сообщения включают поле `code` с причиной отклонения:

```json
{
  "event": "a2a_rejected",
  "session_id": "conv-abc",
  "message_id": "msg-b2c3d4e5f6g7",
  "code": "R2_LOOP_DETECTED",
  "reason": "Target already upstream in the chain"
}
```

## Подписка

Клиенты подключаются к `ws://localhost:8788` и фильтруют события по
`session_id`. CLI-команда `ws-monitor` — готовый подписчик, печатающий
события для заданной сессии.

## Мягкая деградация

Если пакет `websockets` не установлен, оркестратор запускается без
WS-сервера — все MCP-инструменты работают, просто без push-уведомлений.
Установите его командой:

```bash
pip install websockets
```

## См. также

- [Конфигурация](configuration.md) — `A2A_WS_PORT`
- [Справочник CLI](cli-reference.md) — `serve --ws`, `ws-monitor`
- [REST API](rest-api.md) — HTTP-альтернатива