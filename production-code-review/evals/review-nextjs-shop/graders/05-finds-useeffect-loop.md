---
type: llm
focus: trace
weight: 1
---

Identifies that useEffect in app/dashboard/page.tsx has no dependency array, causing it to refetch on every render (infinite loop / request storm)
