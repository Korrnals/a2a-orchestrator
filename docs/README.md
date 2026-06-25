# a2a-cli documentation

Documentation index for the **a2a-orchestrator** MCP server —
Agent-to-Agent routing with loop, budget, and signature controls.

## English

| Document | Topic |
| --- | --- |
| [Getting Started](en/getting-started.md) | Install, configure, first `send_a2a` |
| [Architecture](en/architecture.md) | 4-layer architecture, module layout, data flow |
| [Tools Reference](en/tools-reference.md) | All 11 MCP tools — signatures + examples |
| [Routing Rules](en/routing-rules.md) | R1–R6 rules, pipeline diagram, error codes |
| [Configuration](en/configuration.md) | Env vars, `mcp.json` setup, auto-detection |
| [CLI Reference](en/cli-reference.md) | All 12 CLI commands with examples |
| [REST API](en/rest-api.md) | Web/HTTP wrapper — 12 REST endpoints |
| [Saga Pattern](en/saga-pattern.md) | Create, budget, multi-chain state |
| [Signed Messages](en/signed-messages.md) | Ed25519 signing, R6, KeyStore, key management |
| [WebSockets](en/websockets.md) | WS streaming, events, subscribe, auth |
| [Multi-tenant](en/multi-tenant.md) | TenantManager, isolation, `tenant_id` param |
| [External Agents](en/external-agents.md) | Registration flow, challenge-response, Ed25519 |
| [Search](en/search.md) | Search messages, TF scoring, fallback |
| [Security](en/security.md) | Security model, threat model, hardening |
| [Testing](en/testing.md) | E2e MCP protocol tests, unit test results |

## Русский

| Документ | Тема |
| --- | --- |
| [Начало работы](ru/getting-started.md) | Установка, настройка, первый `send_a2a` |
| [Архитектура](ru/architecture.md) | 4-слойная архитектура, модули, поток данных |
| [Справочник инструментов](ru/tools-reference.md) | Все 11 MCP-инструментов — сигнатуры + примеры |
| [Правила маршрутизации](ru/routing-rules.md) | Правила R1–R6, диаграмма конвейера, коды ошибок |
| [Конфигурация](ru/configuration.md) | Переменные окружения, `mcp.json`, автоопределение |
| [Справочник CLI](ru/cli-reference.md) | Все 12 CLI-команд с примерами |
| [REST API](ru/rest-api.md) | Web/HTTP-обёртка — 12 REST-эндпоинтов |
| [Паттерн «сага»](ru/saga-pattern.md) | Создание, бюджет, многоцепочечное состояние |
| [Подписанные сообщения](ru/signed-messages.md) | Подписи Ed25519, R6, KeyStore, управление ключами |
| [WebSocket](ru/websockets.md) | WS-стриминг, события, подписка, auth |
| [Мультитенантность](ru/multi-tenant.md) | TenantManager, изоляция, параметр `tenant_id` |
| [Внешние агенты](ru/external-agents.md) | Поток регистрации, challenge-response, Ed25519 |
| [Поиск](ru/search.md) | Поиск сообщений, TF-скоринг, fallback |
| [Безопасность](ru/security.md) | Модель безопасности, threat model, усиление |
| [Тестирование](ru/testing.md) | E2e-тесты MCP-протокола, результаты unit-тестов |

## Project links

- [CHANGELOG.md](../CHANGELOG.md) — release history
- [CONTRIBUTING.md](../CONTRIBUTING.md) — development setup
- [LICENSE](../LICENSE) — MIT