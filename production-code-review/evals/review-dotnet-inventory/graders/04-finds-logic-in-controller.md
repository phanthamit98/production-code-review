---
type: llm
focus: trace
weight: 1
---

Identifies that Restock in ProductsController contains business rules (perishable cap, discount pricing) and/or uses DbContext directly, which should be moved to a service layer
