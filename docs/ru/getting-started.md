# Начало работы

Установите, настройте и отправьте первое A2A-сообщение за 5 минут.

## Предварительные требования

- Python 3.11+
- (Опционально) запущенный [Mnemos](https://github.com/Korrnals/mnemos) для долговременного хранения
- JSON-файлы Agent Card, описывающие ваших агентов

## Установка

```bash
git clone https://github.com/Korrnals/a2a-orchestrator.git
cd a2a-orchestrator
pip install -e .

# Опционально: зависимости web-сервера (FastAPI + uvicorn)
pip install -e ".[web]"
```

## Настройка

Все настройки — переменные окружения. Схемы встроены — внешний каталог
не нужен. Карточки агентов автоопределяются из `a2a/agents/` при
разработке в дереве репозитория.

```bash
export A2A_CARDS_DIR=/path/to/agent/cards
export MNEMOS_BASE_URL=http://127.0.0.1:8787
```

Полный справочник переменных — в [Конфигурации](configuration.md).

## Регистрация в VS Code

Добавьте сервер в ваш `mcp.json`:

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

## Первое A2A-сообщение

После регистрации сервера агент вызывает `send_a2a`:

```python
send_a2a(
    target="agent-dba",
    reason="Требуется экспертиза по базе данных",
    summary="Нужна миграция таблицы orders",
    key_decisions=["добавить колонку, а не новую таблицу"],
    open_questions=["нужно ли индексировать новую колонку?"],
    from_id="agent-tech-lead",
    session_id="conv-001",
)
# → {ok: true, reason: "delivered", next_senior: "agent-dba",
#    message_id: "msg-a1b2c3d4e5f6"}
```

Принимающий агент читает сообщение через `load_context`:

```python
load_context(session_id="conv-001", message_id="msg-a1b2c3d4e5f6")
```

## Проверка работоспособности

```bash
# Дымовой тест CLI — отправка + список
a2a-orchestrator send --from agent-a --to agent-b \
  --reason "smoke test" --summary "hello" --session-id test-001
a2a-orchestrator list --session-id test-001

# Статус цепочки
a2a-orchestrator status --session-id test-001
```

## Следующие шаги

- [Справочник инструментов](tools-reference.md) — все 11 MCP-инструментов
- [Правила маршрутизации](routing-rules.md) — R1–R6 с пояснениями
- [Архитектура](architecture.md) — как части связаны между собой