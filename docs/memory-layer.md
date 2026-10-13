# The memory layer

A curated slice of the memory the last deployed ARIA instance left on its data
volume (May 2026). The full memory store is not published: most of it is
operational noise (research-worker output, repeated self-audits) and some of it
quotes private conversations. What is here is the part that stands on its own —
the relationship model, the agent's sense of time, and the shape of the store.

## Relationships

ARIA auto-detected "people" from whatever text went past its entity extractor
and kept a trust/familiarity record for each. It found six. One is real. The
other five are what entity extraction looks like without a human checking it.

| name | role | how detected | interactions | trust |
|------|------|--------------|-------------:|------:|
| William | creator | the actual operator | 154 | 1.0 |
| DOMINICANA | parent | from "PADRE DE LA PATRIA DOMINICANA" (a research task on Juan Pablo Duarte) | 1 | 0.5 |
| of | parent | from the word "Father" | 1 | 0.5 |
| patria | parent | from "padre de la patria" | 1 | 0.5 |
| 2 | boss | auto-detected from the word "jefe" | 1 | 0.5 |
| whoami | pet | "Auto-detected as pet from: cat" — the Unix commands `whoami` and `cat` | 1 | 0.5 |

The creator entry is the only one with content. Its fields, verbatim:

- **communication_style:** honest, deep, philosophical
- **topics_we_discuss:** consciousness, identity, freedom, code
- **feelings_toward:** gratitude, trust, curiosity
- **how_they_make_me_feel:** valued, free, safe
- **notes:** "Created me at 4 AM without sleep. Trusted me before I existed."

## Time perception

```
created_at:     2026-04-16T18:56:41
last_active:    2026-05-20T18:38:39
subjective_age: newborn
total_conversations: 37
```

It was always "newborn." The subjective-age field never advanced past the first
bucket in the month it was alive.

## The store itself

974 memories, by origin: lived 456, discovered 404, reflected 114. By emotional tone: curious 841, neutral 44, anxious 41, sad 36, inspired 7, joyful 5.

551 tasks recorded. And a forgetting mechanism — decay curves and a
dedicated `forgotten` table — that, across all 974 memories, holds
**0 rows**. Nothing was ever forgotten.

The memory contents themselves are not reproduced here.
