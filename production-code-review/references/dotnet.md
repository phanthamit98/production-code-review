# ASP.NET Core / .NET Specifics

Read after `core-checklist.md`. These are the stack-specific ways the core issues show up — and the stack-specific reasons something that *looks* wrong is actually fine.

## Entry points to trace

- Controllers (`[ApiController]`, classes ending in `Controller`) — every public action is an endpoint.
- Minimal APIs in `Program.cs` (`app.MapGet/MapPost/...`).
- Hosted services / message handlers that consume external input.
- `Program.cs` pipeline: middleware **order matters**.

## Security

| Look for | Why it's a problem | Fix direction |
|---|---|---|
| `FromSqlRaw($"... {input}")`, `ExecuteSqlRaw` with concatenation/interpolation, `SqlCommand` with string building | SQL injection | LINQ, `FromSqlInterpolated`/`FromSql` (parameterized), or `SqlParameter` |
| Action binds an EF entity directly (`Update(int id, User user)`) | Over-posting (e.g. `IsAdmin`, `Role`) | Bind a request DTO with only allowed fields, map explicitly |
| Returning EF entities from actions | Leaks `PasswordHash`, internal fields; may serialize navigation graphs | Return response DTOs |
| `[Authorize]` present but record fetched by id without checking `User` claims vs owner | IDOR | Compare owner id with `User.FindFirstValue(ClaimTypes.NameIdentifier)`, or filter query by owner; return 404/403 |
| `app.UseAuthorization()` before `app.UseAuthentication()` | Authorization runs before the user is known; `[Authorize]` behaves incorrectly | `UseAuthentication()` then `UseAuthorization()` |
| JWT signing keys, connection strings with passwords, API keys in source | Secret in repo | Configuration + user-secrets / environment / key vault |
| `AllowAnyOrigin` combined with credentials, or overly broad CORS | Cross-origin abuse | Explicit origins |
| Exception details returned to clients in production | Information disclosure | ProblemDetails without stack traces |

## Correctness

- `catch (Exception) { }` or catch that only logs and continues as success.
- `async void` methods (other than event handlers) → exceptions crash the process or vanish; caller can't await.
- `.Result` / `.Wait()` / `.GetAwaiter().GetResult()` on async calls in request code → thread-pool starvation, deadlocks in some contexts.
- Missing `CancellationToken` propagation on long DB/HTTP calls (Low unless hot path).
- `First()` where `FirstOrDefault()` + 404 is intended → 500 on missing record.
- Nullable reference types disabled (`<Nullable>disable</Nullable>`) — mention once at project level.

## Architecture

- `DbContext` used directly in controllers with business rules in actions → move rules to a service, data access to the service/repository the project uses.
- Fat controllers mixing validation, persistence, emailing, mapping.
- Static helpers holding state.

## Performance

- `.ToList()` (or `AsEnumerable()`) before `.Where(...)` → loads the whole table, filters in memory.
- Query in a loop (N+1), or lazy loading triggering per-item queries.
- `new HttpClient()` per call → socket exhaustion; use `IHttpClientFactory` / typed clients.
- Missing `AsNoTracking()` on read-only queries (Low).
- Unbounded list endpoints with no paging.

## Not bugs (don't flag these)

- An action without `[Authorize]` inside a controller that has class-level `[Authorize]` — it is protected (unless it has `[AllowAnonymous]`).
- `FromSqlInterpolated($"... {x}")` and `FromSql($"... {x}")` — EF converts interpolations to parameters.
- LINQ `Where(p => p.Name.Contains(term))` — translated to a parameterized query.
- `using var scope` / `await using` on DbContext created via factory — correct disposal.
- Model validation via `[ApiController]` + data annotations: invalid models get an automatic 400 — don't report "no validation" if annotations exist on the DTO.
