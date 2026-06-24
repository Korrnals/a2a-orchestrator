# Search

The `search_messages` tool searches A2A message content for relevant
past conversations. It uses Mnemos's search API when available; falls
back to substring search on the JSONL fallback file when Mnemos is
unreachable.

## Properties

| Property | Value |
| --- | --- |
| Matching | TF-style substring scoring on `summary`, `reason`, `key_decisions`, `open_questions` |
| Scope | Session-scoped (`session_id` provided) or global |
| Ranking | Score descending; top `limit` results |
| Fallback | JSONL `MessageStore.load_all()` when Mnemos is down |

## Usage

```python
search_messages(query="orders migration", session_id="conv-abc", limit=5)
# → {ok: true, results: [{message, score, session_id, message_id}, ...], count: N}
```

### Global search (all sessions)

```python
search_messages(query="database schema", limit=10)
```

### Tenant-scoped search

```python
search_messages(query="migration", tenant_id="acme-corp", limit=5)
```

## Result format

Each result contains the full message, a relevance score, the session
id, and the message id:

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

## Scoring

The scorer tokenises the query into terms and counts occurrences
across the searchable fields. Fields are weighted: `summary` and
`reason` carry more weight than `key_decisions` and `open_questions`.
Results are ranked by total score, descending.

## Fallback behavior

When Mnemos is unavailable, the search falls back to loading all
messages from the JSONL store (`MessageStore.load_all()`) and running
the same scoring algorithm in-memory. This is slower for large
datasets but ensures search always works.

## CLI

```bash
a2a-orchestrator search "orders migration" --limit 5
```

## See also

- [Tools Reference](tools-reference.md) — `search_messages` signature
- [Architecture](architecture.md) — persistence and fallback
- [CLI Reference](cli-reference.md) — `search` command