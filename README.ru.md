<!-- markdownlint-disable MD041 MD033 -->
<p align="center">
  <img src="docs/assets/a2a-banner.svg" alt="a2a-cli" width="100%">
</p>

<h1 align="center">a2a-orchestrator</h1>

<p align="center">
  <strong>MCP-сервер A2A-маршрутизации</strong><br>
  <em>Передача задач между AI-агентами с контролем циклов, бюджета и подписей</em>
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="Лицензия: MIT"></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/version-0.9.0-blue.svg" alt="Версия"></a>
  <a href="tests/"><img src="https://img.shields.io/badge/tests-241%20passing-brightgreen.svg" alt="Тесты"></a>
  <a href="https://docs.astral.sh/ruff/"><img src="https://img.shields.io/badge/code%20style-ruff-000000.svg" alt="Стиль кода: ruff"></a>
</p>

<p align="center">
  <a href="README.md">🇬🇧 English</a> · <strong>🇷🇺 Русский</strong>
</p>

<p align="center">
  <a href="docs/ru/getting-started.md">Быстрый старт</a> ·
  <a href="docs/ru/tools-reference.md">Инструменты</a> ·
  <a href="docs/ru/architecture.md">Архитектура</a> ·
  <a href="docs/ru/configuration.md">Конфигурация</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

---

## Зачем?

В типичной мультиагентной схеме при делегировании от Агента А к Агенту Б
пересылается весь транскрипт разговора — это стоит в **30–45×** больше
токенов, чем структурированное сообщение. `a2a-cli` заменяет
пересылку транскрипта структурированным сообщением о передаче и
контролирует границы безопасности (белый список, защита от циклов,
лимиты глубины и бюджета, проверка подписей, согласие на деструктивные
действия).

## Ключевые возможности

| Возможность | Детали |
| --- | --- |
| **11 MCP-инструментов** | `send_a2a`, `create_saga`, `load_context`, `get_chain_status`, `get_metrics`, `get_saga_status`, `search_messages`, регистрация, `list_tenants` |
| **6 правил маршрутизации (R1–R6)** | Белый список, циклы, глубина, бюджет, подпись, деструктивное согласие |
| **Паттерн «сага»** | Многоцепочечное состояние, бюджет 6 вызовов на сагу |
| **Подписанные сообщения** | Подписи Ed25519, канонический JSON, проверка R6 |
| **WebSocket-стриминг** | Вещание событий в реальном времени на порту 8788 |
| **REST API** | Обёртка FastAPI на порту 8789, 12 эндпоинтов |
| **Мультитенантность** | Изоляция по тенантам, `TenantManager` |
| **Внешние агенты** | Регистрация challenge-response через Ed25519 |
| **Поиск** | TF-скоринг с fallback Mnemos→JSONL |
| **241 тест** | Unit + e2e, все проходят |

## Быстрый старт

**Установка в одну команду** (создаёт venv, устанавливает из GitHub,
опционально регистрирует в VS Code `mcp.json`):

```bash
curl -fsSL https://raw.githubusercontent.com/Korrnals/a2a-orchestrator/main/scripts/install.sh | bash
```

**Установка вручную** (для разработки):

```bash
git clone https://github.com/Korrnals/a2a-orchestrator.git
cd a2a-cli
pip install -e .
# Добавьте в VS Code mcp.json — см. docs/ru/getting-started.md
python3 -m a2a_orchestrator
```

<details>
<summary>Параметры установки</summary>

```bash
# Конкретная версия
curl -fsSL https://raw.githubusercontent.com/Korrnals/a2a-orchestrator/main/scripts/install.sh | bash -s -- --version 1.0.0

# Автоматическая настройка MCP (без запроса)
curl -fsSL https://raw.githubusercontent.com/Korrnals/a2a-orchestrator/main/scripts/install.sh | bash -s -- --mcp

# Без venv (в системный Python)
curl -fsSL https://raw.githubusercontent.com/Korrnals/a2a-orchestrator/main/scripts/install.sh | bash -s -- --no-venv

# Свой путь venv + uv
curl -fsSL https://raw.githubusercontent.com/Korrnals/a2a-orchestrator/main/scripts/install.sh | bash -s -- --venv ~/.my-venv --uv
```

Скрипт установки:

- Создаёт venv в `~/.a2a-orchestrator/venv`
- Устанавливает пакет из GitHub
- Создаёт лаунчер в `~/.local/bin/a2a-orchestrator`
- Опционально регистрирует в VS Code `mcp.json`

</details>

## Удаление

```bash
curl -fsSL https://raw.githubusercontent.com/Korrnals/a2a-orchestrator/main/scripts/uninstall.sh | bash
```

Удаляет venv, лаунчер и запись в `mcp.json`.

## Документация

- [Начало работы](docs/ru/getting-started.md)
- [Справочник инструментов](docs/ru/tools-reference.md)
- [Архитектура](docs/ru/architecture.md)
- [Правила маршрутизации (R1–R6)](docs/ru/routing-rules.md)
- [Конфигурация](docs/ru/configuration.md)
- [Справочник CLI](docs/ru/cli-reference.md)
- [REST API](docs/ru/rest-api.md)
- [Безопасность](docs/ru/security.md)
- [Тестирование](docs/ru/testing.md)

Полный индекс документации: [docs/](docs/README.md)

## Лицензия

[MIT](LICENSE) — © 2026 контрибьюторы a2a-orchestrator.
