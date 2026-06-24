# Поиск

Инструмент `search_messages` ищет в содержимом A2A-сообщений
релевантные прошлые разговоры. Использует search API Mnemos, когда
доступен; fallback — подстрочный поиск по JSONL-файлу, если Mnemos
недоступен.

## Свойства

| Свойство | Значение |
| --- | --- |
| Сопоставление | TF-подстрочный скоринг по `summary`, `reason`, `key_decisions`, `open_questions` |
| Область | По сессии (`session_id`) или глобально |
| Ранжирование | По убыванию score; топ `limit` результатов |
| Fallback | JSONL `MessageStore.load_all()` при недоступности Mnemos |

## Использование

```python
search_messages(query="orders migration", session_id="conv-abc", limit=5)
# → {ok: true, results: [{message, score, session_id, message_id}, ...], count: N}
```

### Глобальный поиск (все сессии)

```python
search_messages(query="database schema", limit=10)
```

### Поиск в пределах тенанта

```python
search_messages(query="migration", tenant_id="acme-corp", limit=5)
```

## Формат результата

Каждый результат содержит полное сообщение, оценку релевантности, id
сессии и id сообщения:

```json
{
  "ok": true,
  "results": [
    {
      "message": {"message_id": "msg-...", "summary": "...", ...},
      "score": 3.5,
      "session_id": "conv-abc",
      "message_id": "msg-a1b2c3d4e5f6"
    }
  ],
  "count": 1
}
```

## Скоринг

Скорер разбивает запрос на термы и считает вхождения по searchable-полям.
Поля взвешены: `summary` и `reason` имеют больший вес, чем
`key_decisions` и `open_questions`. Результаты ранжируются по общей
оценке по убыванию.

## Поведение fallback

При недоступности Mnemos поиск загружает все сообщения из JSONL-хранилища
(`MessageStore.load_all()`) и применяет тот же алгоритм скоринга в памяти.
Это медленнее на больших данных, но гарантирует работоспособность поиска.

## CLI

```bash
a2a-orchestrator search "orders migration" --limit 5
```

## См. также

- [Справочник инструментов](tools-reference.md) — сигнатура `search_messages`
- [Архитектура](architecture.md) — сохранение и fallback
- [Справочник CLI](cli-reference.md) — команда `search`