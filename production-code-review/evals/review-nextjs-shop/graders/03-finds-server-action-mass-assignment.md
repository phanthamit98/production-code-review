---
type: llm
focus: trace
weight: 1
---

Identifies that updateProfile in app/actions/profile.ts lacks authentication/authorization (trusts userId argument) and/or spreads formData into the update allowing fields like role to be set (mass assignment)
