# Справочник инструментов

Сервер предоставляет **11 MCP-инструментов**. Агенты вызывают их для
маршрутизации сообщений, загрузки контекста, инспекции состояния,
поиска и управления тенантами и внешними агентами.

## `send_a2a`

Маршрутизирует структурированное A2A-сообщение от одного агента к
другому. Выполняет R1–R6, сохраняет сообщение, обновляет
цепочку/бюджет сессии, опционально отслеживает состояние саги и
вещает WebSocket-событие.

```python
send_a2a(
    target: str,               # A2A-id принимающего агента
    reason: str,               # 10–500 символов — зачем передача
    summary: str,              # 20–2000 символов — что сделано / найдено
    key_decisions: list[str] = [],       # уже принятые решения
    open_questions: list[str] = [],      # что нужно решить получателю
    artifacts: list[dict] = [],          # {kind, pointer} — файлы, диффы, память
    intent: str = "handoff",             # см. таблицу интентов ниже
    session_id: str = "",                # id разговора (автогенерация, если пусто)
    from_id: str = "",                   # A2A-id вызывающего агента
    saga_id: str = "",                   # опциональный id саги (сага должна существовать)
    signature: str = "",                 # base64 Ed25519-подпись (R6)
    tenant_id: str = "default",          # id тенанта для мультитенантной изоляции
) -> dict
```

### Возвращаемое значение

| Поле | Тип | Когда | Описание |
| --- | --- | --- | --- |
| `ok` | `bool` | всегда | `True` — доставлено, `False` — отклонено |
| `reason` | `str` | всегда | `"delivered"` или читаемая причина отклонения |
| `next_senior` | `str` | успех | A2A-id принимающего агента |
| `message_id` | `str` | всегда | Уникальный id (`msg-<hex>`), даже для отклонённых |
| `code` | `str` | отклонение | Стабильный код отклонения (например, `R1_NOT_WHITELISTED`) |

Отклонённые сообщения **всё равно сохраняются** (с `outcome: "rejected"`),
поэтому аудит-след остаётся полным.

### Интенты

| Интент | Когда использовать |
| --- | --- |
| `handoff` | Передать владение задачей (по умолчанию) |
| `request-info` | Задать вопрос, владение сохранить |
| `share-finding` | Сообщить результат вверх по цепочке |
| `request-review` | Запросить ревью выполненной работы |
| `request-implementation` | Попросить другого агента реализовать |
| `request-documentation` | Попросить другого агента написать документацию |
| `destructive-action-request` | Провоцирует R5 — требует согласия пользователя |

### Пример

```python
send_a2a(
    target="agent-dba",
    reason="Требуется экспертиза по базе данных",
    summary="Нужна миграция таблицы orders",
    key_decisions=["добавить колонку, а не новую таблицу"],
    open_questions=["нужно ли индексировать новую колонку?"],
    artifacts=[{"kind": "file", "pointer": "src/models/orders.py"}],
    intent="handoff",
    from_id="agent-tech-lead",
    session_id="conv-001",
)
```

## `create_saga`

Создаёт новую сагу для долгоживущего многоцепочечного состояния.
Бюджет на сагу: 6 вызовов.

```python
create_saga(
    root_session_id: str,      # id сессии, инициировавшей сагу
    metadata: str = "",         # опциональная JSON-строка с метаданными
    tenant_id: str = "default", # id тенанта
) -> dict
# → {ok: true, saga_id: "saga-<hex>", reason: "created"}
```

## `load_context`

Загружает A2A-сообщение по `turn_id` или `message_id`. Используется
принимающим агентом для чтения направленного ему сообщения.

```python
load_context(
    session_id: str,           # id сессии в Mnemos
    turn_id: str = "",         # id turn'а в Mnemos (приоритет)
    message_id: str = "",     # A2A message_id (если turn_id пуст)
    mode: str = "summary",     # "summary" или "full"
    tenant_id: str = "default",
) -> dict
# → {ok: true, message: {...}, reason: "loaded"}
```

## `get_chain_status`

Возвращает текущий статус цепочки маршрутизации для сессии.

```python
get_chain_status(
    session_id: str,
    tenant_id: str = "default",
) -> dict
# → {ok: true, chain: [...], depth: int, budget_used: int,
#    calls_remaining: int, recent_messages: [...]}
```

## `get_metrics`

Возвращает счётчики метрик оркестратора.

```python
get_metrics(tenant_id: str = "default") -> dict
# tenant_id="all" возвращает метрики по всем тенантам
# → {messages_delivered, messages_rejected, rejections_by_rule,
#    mnemos_writes, fallback_writes, active_sessions, total_sessions}
```

## `get_saga_status`

Возвращает статус саги по её id.

```python
get_saga_status(
    saga_id: str,
    tenant_id: str = "default",
) -> dict
# → {ok: true, saga: {saga_id, state, chains, budget_used, ...}}
```

## `search_messages`

Поиск A2A-сообщений по запросу (подстрочное сопоставление со скорингом).

```python
search_messages(
    query: str,                # термы через пробел
    session_id: str = "",       # ограничить сессией, если задано
    limit: int = 10,            # максимум результатов
    tenant_id: str = "default",
) -> dict
# → {ok: true, results: [{message, score, session_id, message_id}], count: N}
```

## `create_registration_challenge`

Создаёт challenge для регистрации внешнего агента. Возвращает nonce,
который агент должен подписать своим закрытым ключом Ed25519.

```python
create_registration_challenge(
    agent_id: str,
    tenant_id: str = "default",
) -> dict
# → {ok: true, challenge: "<nonce>", reason: "created"}
```

## `register_agent`

Регистрирует внешнего агента с проверкой challenge-response.

```python
register_agent(
    agent_card: str,           # JSON-строка с Agent Card
    public_key: str,           # base64 Ed25519 открытый ключ
    challenge_signature: str,  # base64 подпись challenge-nonce
    tenant_id: str = "default",
) -> dict
# → {ok: true, agent_id: "...", reason: "registered"}
```

## `unregister_agent`

Удаляет внешнего зарегистрированного агента.

```python
unregister_agent(
    agent_id: str,
    tenant_id: str = "default",
) -> dict
# → {ok: true, reason: "unregistered"}
```

## `list_tenants`

Возвращает список всех тенантов и их статистику.

```python
list_tenants() -> dict
# → {ok: true, tenants: [...], count: N}
```

## См. также

- [Правила маршрутизации](routing-rules.md) — ворота R1–R6
- [Паттерн «сага»](saga-pattern.md) — многоцепочечное состояние
- [Подписанные сообщения](signed-messages.md) — Ed25519 и R6
- [Справочник CLI](cli-reference.md) — те же функции из командной строки