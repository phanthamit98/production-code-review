---
type: llm
focus: trace
weight: 1
---

Identifies that DELETE in app/api/orders/[id]/route.ts deletes any order by id without checking it belongs to the current user (IDOR / missing ownership check)
