# Core Checklist (all stacks)

Work through the sections in order. Each item is a question to ask of the code, followed by why it matters.

## 1. Security

- **Injection** — Does any user-controlled value reach a SQL string, shell command, file path, regex, or template without parameterization/escaping? String concatenation or interpolation into a raw query is the classic Critical.
- **Authentication** — Can an unauthenticated caller reach this entry point? Check middleware and class/route-level guards before concluding "no auth".
- **Authorization / IDOR** — Being logged in is not the same as being allowed. When a record is fetched/changed by an id from the request, is ownership or role checked? This is the most commonly missed High.
- **Mass assignment / over-posting** — Is a request body or form spread directly into a database update/create? A user can then set fields like `role`, `isAdmin`, `balance`, `ownerId`.
- **Trusting the client** — Prices, totals, user ids, roles, discounts coming from the request must be recomputed or looked up on the server.
- **Sensitive data exposure** — Do responses return password hashes, tokens, internal ids, full entities, stack traces? Are secrets hardcoded or shipped to the browser?
- **XSS** — Is untrusted HTML rendered without sanitization?
- **Webhooks / callbacks** — Is the signature verified before the payload is trusted?
- **SSRF / open redirect** — Does a user-controlled URL get fetched or redirected to?

## 2. Correctness & error handling

- Are errors **swallowed** (empty catch, catch that logs nothing and returns success)? Silent failure turns bugs into data loss.
- Does the code return a success status (200) when the operation failed?
- Are error messages to the client meaningful but free of internals?
- Edge cases: empty collections, null/undefined, missing records (404 vs 500), concurrency, double submission.
- Async correctness: missing `await`, fire-and-forget work that can fail unobserved, blocking on async code.
- Resource handling: connections, clients, streams disposed/reused correctly.

## 3. Architecture & layering

- **Controllers / route handlers / Server Actions should be thin**: parse + validate input, check auth, call a service, map the result to a response.
- Business rules (pricing, permissions, workflows) belong in a service/domain layer, not in UI components or route files.
- Data access belongs in a repository/data layer (or a clearly separated module), not scattered through handlers and components.
- Is existing shared code (helpers, services, validation schemas) reused, or duplicated?
- Report layering problems as Medium unless they directly cause a bug; explain the concrete cost (untestable, duplicated rules that will drift).

## 4. Type safety

- `any` / `object` / `dynamic` at boundaries (request bodies, API responses, public functions) hide bugs; prefer validated, typed input.
- Unchecked casts (`as User`, `(User)obj`) on external data.
- Nullable handling: `!` / null-forgiving operators that paper over real null cases.
- Public APIs should have explicit types.

## 5. Performance

Only report what has real cost at realistic scale.

- **N+1 queries** — a query inside a loop.
- Loading whole tables then filtering in memory.
- Missing pagination on list endpoints that can grow unbounded.
- Re-creating expensive objects per call (HTTP clients, DB clients).
- Unnecessary re-renders or effects that run in a loop (React).

## 6. Maintainability

- Dead code, unused imports, commented-out blocks.
- Misleading names; functions doing several unrelated things.
- Magic numbers/strings that encode business rules.
- Group these; keep them Low unless they hide a bug.
