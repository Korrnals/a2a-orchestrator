# Мультитенантность

Оркестратор поддерживает изоляцию по тенантам. У каждого тенанта свой
реестр Agent Card, хранилище сессий, хранилище сообщений, метрики,
хранилище саг и хранилище ключей.

## Свойства

| Свойство | Значение |
| --- | --- |
| Тенант по умолчанию | `"default"` (backward compat — все вызовы без `tenant_id` используют его) |
| Изоляция | Полная: реестр, сессии, метрики, саги, ключи |
| Управление | `TenantManager` создаёт и кэширует `TenantContext` по требованию |
| Каталог карточек | Тенант по умолчанию использует `A2A_CARDS_DIR`; остальные — `cards_dir / tenant_id` |

## Использование `tenant_id`

Передавайте параметр `tenant_id` в инструменты, которые его поддерживают:

| Инструмент | Параметр `tenant_id` |
| --- | --- |
| `send_a2a` | `tenant_id` (по умолчанию `"default"`) |
| `get_chain_status` | `tenant_id` |
| `get_metrics` | `tenant_id` (используйте `"all"` для всех тенантов) |
| `get_saga_status` | `tenant_id` |
| `search_messages` | `tenant_id` |
| `create_saga` | `tenant_id` |
| `create_registration_challenge` | `tenant_id` |
| `register_agent` | `tenant_id` |
| `unregister_agent` | `tenant_id` |

## Список тенантов

```python
list_tenants()
# → {ok: true, tenants: [{tenant_id, sessions, agents, ...}], count: N}
```

Или через CLI:

```bash
a2a-cli tenants list
```

## TenantManager

`TenantManager` — центральный объект, создающий и кэширующий экземпляры
`TenantContext`. Каждый `TenantContext` включает:

- `registry` — реестр Agent Card (карточки по тенантам)
- `session_store` — цепочка/глубина/бюджет сессий
- `message_store` — JSONL-fallback по тенантам
- `metrics` — счётчики по тенантам
- `saga_store` — саги по тенантам
- `key_store` — ключи Ed25519 по тенантам

Тенант по умолчанию создаётся активно при импорте для обратной
совместимости. Остальные — при первом обращении.

## Структура каталога карточек

```text
$A2A_CARDS_DIR/
├── agent-tech-lead.json      # тенант по умолчанию
├── agent-dba.json
└── acme-corp/                # тенант "acme-corp"
    ├── agent-a.json
    └── agent-b.json
```

Тенант по умолчанию загружает карточки из корня `A2A_CARDS_DIR`. Тенант
`acme-corp` — из `A2A_CARDS_DIR/acme-corp/`.

## См. также

- [Конфигурация](configuration.md) — `A2A_CARDS_DIR`
- [Внешние агенты](external-agents.md) — регистрация по тенантам
- [Справочник инструментов](tools-reference.md) — `list_tenants`