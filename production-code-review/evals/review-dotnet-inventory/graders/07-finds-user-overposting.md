---
type: llm
focus: trace
weight: 1
---

Identifies that UsersController.Update binds the User entity directly, allowing over-posting of fields such as IsAdmin or PasswordHash (and/or lets any user update any other user)
