# InventoryApi: Pre-Production Code Review

**Scope:** Every source file under `InventoryApi/` (Program.cs, the controllers, the services, the models, the DTOs, the DbContext and the csproj). That is about 316 lines.
**Stack:** ASP.NET Core 8, EF Core 8 (SQL Server), JWT bearer auth.
**Verdict: NOT READY FOR PRODUCTION.** There are 5 Critical blockers. They include SQL injection, a hardcoded signing key, and privilege escalation to admin by any logged-in user. There is also a middleware ordering bug that makes every endpoint return 401. Fix every Critical and High item before deploying.

## Summary

| # | Severity | Area | Location | Issue |
|---|----------|------|----------|-------|
| 1 | Critical | Security | ProductsController.cs:18 | SQL injection via `FromSqlRaw` with string interpolation |
| 2 | Critical | Security | UsersController.cs:20-28 | Mass assignment: any user can edit any account, set `IsAdmin = true`, and overwrite `PasswordHash` |
| 3 | Critical | Security | UsersController.cs:13-18 | Any user can read any user record, including `PasswordHash` and `IsAdmin` |
| 4 | Critical | Security | Program.cs:24-25 | JWT signing key is hardcoded in source |
| 5 | Critical | Correctness | Program.cs:37-38 | `UseAuthorization` runs before `UseAuthentication`, so every `[Authorize]` endpoint returns 401 |
| 6 | High | Security | OrdersController.cs:13-18 | IDOR: any user can read any order by ID |
| 7 | High | Security | ProductsController.cs:54 | Any authenticated user can restock products and trigger price changes (no role check) |
| 8 | High | Correctness | OrderService.cs:33-42 | Exception swallowed: cancel reports success even when the save failed |
| 9 | High | Reliability | OrderService.cs:45-49 | `async void` fire-and-forget can crash the process |
| 10 | High | Reliability | OrdersController.cs:24 | Sync-over-async `.Result` risks thread-pool starvation |
| 11 | High | Performance | OrderService.cs:21-24 | Loads the entire Orders table into memory to filter one user's orders |
| 12 | High | Correctness | ProductsController.cs:65-69 | Discount compounds on every restock above 1000 units |
| 13 | High | Correctness | ProductsController.cs:57-72 | Lost-update race on `Stock` (no concurrency control) |
| 14 | Medium | Reliability | ReportService.cs:16 | `new HttpClient()` per call: socket exhaustion, no timeout |
| 15 | Medium | Correctness | OrderService.cs:27-32 | Orders in any status can be cancelled, including already shipped or already cancelled ones |
| 16 | Medium | Robustness | OrdersController.cs:23,31 | `int.Parse` on a claim that may be missing returns 500 instead of 401 |
| 17 | Medium | Correctness | UsersController.cs:25-26 | `Update` on a missing ID throws `DbUpdateConcurrencyException` and returns 500 |
| 18 | Medium | Performance | ProductsController.cs:14-33 | `search` and `category` endpoints are unbounded (no paging) |
| 19 | Medium | Data | Models/Entities.cs, AppDbContext.cs | No decimal precision, string lengths, indexes, unique email, FK or migrations |
| 20 | Medium | Ops | Program.cs | No global exception handler, HSTS, health checks, rate limiting or config validation |
| 21 | Medium | Design | Users/OrdersController | EF entities returned and accepted directly instead of DTOs |
| 22 | Low | Misc | various | No CancellationToken propagation, magic strings and numbers, unused `IReportService`, no tests |

---

## Critical

### 1. SQL injection in product search
`Controllers/ProductsController.cs:18`
```csharp
.FromSqlRaw($"SELECT * FROM Products WHERE Name LIKE '%{term}%'")
```
`term` comes straight from the query string and is concatenated into raw SQL. For example, `?term=' ; DROP TABLE Users; --` would be executed. `FromSqlRaw` does not parameterize C# interpolation.
(The `category` endpoint on line 28 uses `FromSqlInterpolated` correctly and is safe.)

**Fix:** Use LINQ. You don't need raw SQL here:
```csharp
var products = await db.Products.AsNoTracking()
    .Where(p => EF.Functions.Like(p.Name, $"%{term}%"))
    .OrderBy(p => p.Name).Take(50)
    .Select(p => new ProductResponse(p.Id, p.Name, p.Category, p.Price, p.Stock))
    .ToListAsync(ct);
```
If you need raw SQL, use `FromSqlInterpolated` or `FromSql`, or pass `SqlParameter`s. Also escape `%`, `_` and `[` in `term` if users should not be able to send wildcards.

### 2. Privilege escalation and account takeover via `PUT /api/users/{id}`
`Controllers/UsersController.cs:20-28`
```csharp
public async Task<IActionResult> Update(int id, User user)
{
    if (id != user.Id) return BadRequest();
    db.Users.Update(user);
```
- There is no check that the caller is that user or an admin. Any authenticated user can update any account.
- The endpoint binds the full `User` entity (mass assignment). A caller can send `"isAdmin": true` to make themselves admin, or set `passwordHash` to a hash they control and take over any account, including admin accounts.
- `Update()` overwrites every column, so any field the caller leaves out (for example `PasswordHash`) is reset to an empty string.

**Fix:** Accept an `UpdateUserRequest` DTO that contains only the editable fields (for example `DisplayName`). Load the entity, check `id == currentUserId || User.IsInRole("Admin")`, copy the allowed fields onto it, and save. Change `IsAdmin` and the password only through separate, admin-only or password-verified flows.

### 3. User records and password hashes exposed via `GET /api/users/{id}`
`Controllers/UsersController.cs:13-18`
The endpoint returns the raw `User` entity, including `PasswordHash` and `IsAdmin`, to any authenticated user for any ID. IDs are sequential integers, so an attacker can dump every user's email and password hash and crack the hashes offline.

**Fix:** Return a `UserResponse(Id, DisplayName[, Email])` DTO and never serialize `PasswordHash`. Restrict the endpoint to the user themselves or to admins.

### 4. Hardcoded JWT signing key
`Program.cs:24-25`
```csharp
IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes("inventory-super-secret-signing-key-2024!!"))
```
Anyone with access to the repository (or a decompiled DLL) can mint valid tokens for any user, including admins. Rotating the key also requires a redeploy.

**Fix:** Load the key from configuration backed by a secret store (Azure Key Vault, AWS Secrets Manager, environment variable, or user-secrets in development). Fail at startup if it is missing or shorter than 256 bits. Rotate the current key, because it is now compromised. Also consider setting `ValidateIssuerSigningKey = true`, `ClockSkew = TimeSpan.FromMinutes(1)` and `ValidAlgorithms = [SecurityAlgorithms.HmacSha256]`, and moving issuer and audience into config.

### 5. Authentication and authorization middleware are in the wrong order
`Program.cs:37-38`
```csharp
app.UseAuthorization();
app.UseAuthentication();
```
Authorization runs before the bearer token has been authenticated. At that point `HttpContext.User` is anonymous, and the default policy has no explicit schemes, so every `[Authorize]` endpoint returns 401. Every controller is `[Authorize]`, so the API would be unusable in production. Someone may then "fix" this by removing `[Authorize]`, which would be much worse.

**Fix:**
```csharp
app.UseAuthentication();
app.UseAuthorization();
```

---

## High

### 6. IDOR on `GET /api/orders/{id}`
`Controllers/OrdersController.cs:13-18`, `Services/OrderService.cs:16-17`
Any authenticated user can read any order by enumerating IDs. `CancelAsync` scopes by `userId`, but `GetByIdAsync` does not.
**Fix:** Change the method to `GetByIdAsync(int id, int userId)` and filter on `o.UserId == userId`, unless the caller is an admin. Return 404, not 403, so the endpoint doesn't reveal whether an order exists.

### 7. Restock is not role-restricted
`Controllers/ProductsController.cs:54`
Any authenticated user can add stock, and as a side effect lower the price (see #12). Inventory mutation should be limited to staff or admins.
**Fix:** Add `[Authorize(Roles = "Admin")]` or a named policy. Note that `User.IsAdmin` is currently never turned into a role claim, so you need a role or `isAdmin` claim in the token.

### 8. Swallowed exception in order cancellation
`Services/OrderService.cs:33-42`
```csharp
try { await db.SaveChangesAsync(); } catch (Exception) { }
NotifyCancellation(order.Id);
return true;
```
If the save fails (database down, deadlock, concurrency conflict), the client gets 204 and a cancellation notification goes out, but the order is not cancelled. The failure is also never logged.
**Fix:** Remove the empty catch. If you need to handle specific exceptions (for example `DbUpdateConcurrencyException`), log them and return a failure result. Send the notification only after a successful save.

### 9. `async void` fire-and-forget
`Services/OrderService.cs:45-49`
An exception thrown in an `async void` method cannot be caught and terminates the process. The work is also not awaited and is not tied to the request lifetime or to graceful shutdown.
**Fix:** Make it `async Task` and await it. For real background notifications, write to a queue or outbox, or use a `Channel<T>` consumed by a `BackgroundService`.

### 10. Sync-over-async in `GET /api/orders/mine`
`Controllers/OrdersController.cs:21-26`
```csharp
var result = orders.GetForUserAsync(userId).Result;
```
This blocks a thread-pool thread for each request and can cause thread-pool starvation under load. It also wraps exceptions in `AggregateException`.
**Fix:** `public async Task<IActionResult> Mine(CancellationToken ct) { ... await orders.GetForUserAsync(userId, ct) ... }`.

### 11. Entire Orders table loaded into memory
`Services/OrderService.cs:21-24`
```csharp
var all = await db.Orders.AsNoTracking().ToListAsync();
return all.Where(o => o.UserId == userId)...
```
Every call reads every order in the database. This gets worse as the table grows and can run the server out of memory.
**Fix:** Do the filtering, sorting and paging in SQL:
```csharp
db.Orders.AsNoTracking().Where(o => o.UserId == userId)
  .OrderByDescending(o => o.CreatedAt).Take(100).ToListAsync(ct);
```
Add an index on `(UserId, CreatedAt)`.

### 12. Discount compounds on every restock
`Controllers/ProductsController.cs:65-69`
Once a product's stock is above 1000, every later restock, even of 1 unit, cuts the price by another 10%. Repeated small restocks (which anyone can trigger, see #7) push the price toward 0. A restock endpoint changing the price as a side effect is also surprising.
**Fix:** Confirm the intended rule with the business. Most likely the discount should apply once, when stock crosses the threshold (`product.Stock <= threshold && newStock > threshold`), or pricing should live in a separate, explicit operation. Move `1000`, `500`, `0.9m` and `"Perishable"` into configuration or named constants.

### 13. Lost updates on stock
`Controllers/ProductsController.cs:57-72`
The endpoint reads stock, modifies it and writes it back with no concurrency token. Two concurrent restocks can overwrite each other, and the 500-unit perishable cap can be exceeded.
**Fix:** Add a `[Timestamp] public byte[] RowVersion` to `Product` and handle `DbUpdateConcurrencyException` (retry or return 409). Alternatively, use an atomic update: `ExecuteUpdateAsync(s => s.SetProperty(p => p.Stock, p => p.Stock + qty))` with the cap in the `Where` clause.

---

## Medium

### 14. `HttpClient` created per call
`Services/ReportService.cs:16`
Creating and disposing an `HttpClient` on every call leads to socket exhaustion (TIME_WAIT) under load, and the client ignores DNS changes. There is also no timeout beyond the 100 s default and no retry policy.
**Fix:** Register it with `builder.Services.AddHttpClient<IReportService, ReportService>(c => { c.BaseAddress = ...; c.Timeout = TimeSpan.FromSeconds(10); })` and add resilience (`Microsoft.Extensions.Http.Resilience`). Validate `Rates:BaseUrl` at startup with `ValidateOnStart()`, not on first request.

### 15. Cancel ignores order status
`Services/OrderService.cs:27-32`
Orders that are already shipped, delivered or cancelled can be "cancelled" again, which also sends duplicate notifications.
**Fix:** Only allow the transition from `Pending` (or from whatever states are cancellable). Return 409 otherwise. Replace the `Status` string with an enum.

### 16. `int.Parse` on the NameIdentifier claim
`Controllers/OrdersController.cs:23,31`
If a token has no `sub`/NameIdentifier claim, or a non-numeric one, the `!` and `int.Parse` throw and the endpoint returns 500.
**Fix:** Add a helper that uses `int.TryParse` and returns `Unauthorized()` / `Forbid()` on failure.

### 17. `Update` on a non-existent user returns 500
`Controllers/UsersController.cs:25-26`
`db.Users.Update(detached)` with an ID that doesn't exist throws `DbUpdateConcurrencyException`. The load-then-modify pattern from #2 fixes this as well (return 404).

### 18. Unbounded queries
`Controllers/ProductsController.cs:14-33`
`search` and `category/{category}` return every matching row, which allows a cheap denial of service against a large catalog. Leading-wildcard `LIKE '%x%'` (also used by `List` via `Contains`) can't use an index and scans the whole table.
**Fix:** Add paging (`page` and `pageSize` with a maximum, as `List` already does), require a minimum term length, and consider full-text search for name lookups.

### 19. Data model and schema gaps
`Models/Entities.cs`, `Data/AppDbContext.cs`
- `decimal Price` and `Total` have no precision configured. EF logs a warning and silently uses `decimal(18,2)`. Set it explicitly with `HasPrecision(18, 2)` or `[Precision]`.
- Every string maps to `nvarchar(max)`, which can't be indexed efficiently. Add `HasMaxLength`.
- There is no unique index on `User.Email`, so duplicate accounts are possible.
- There is no FK or navigation from `Order.UserId` to `User`, so orphaned orders are possible.
- There are no indexes on `Product.Category`, `Product.Name` or `Order.UserId`.
- `Order.CreatedAt` has no default and no UTC convention. Use `DateTime.UtcNow` or `DateTimeOffset`, or a database default.
- No EF migrations are checked in, so there is no reproducible way to create or upgrade the production schema.
- There are no `CHECK` constraints for `Stock >= 0` or `Price >= 0`.

### 20. Missing production plumbing in `Program.cs`
- There is no `UseExceptionHandler` or `AddProblemDetails`, so unhandled exceptions return bare 500s with no consistent body.
- There is no `UseHsts()` outside development.
- There are no health checks (`AddHealthChecks().AddDbContextCheck<AppDbContext>()` with `MapHealthChecks("/health")`) for load balancers and orchestrators.
- There is no rate limiting (`AddRateLimiter`), which matters especially for search.
- `GetConnectionString("Default")` may be null, and no `appsettings*.json` exists in the project. This fails only at the first query, so validate it at startup.
- Consider `EnableRetryOnFailure()` on `UseSqlServer` for transient SQL errors.
- No endpoint or service issues tokens. Confirm which identity provider issues tokens with the `inventory-api` issuer and `sub` claim, and that it includes role claims.

### 21. Entities used as the API contract
`UsersController` returns and accepts `User`, and `OrdersController` returns `Order`. This leaks internal fields (#3), enables over-posting (#2), and couples the database schema to the public API.
**Fix:** Use request and response DTOs everywhere, as `ProductsController` already does.

---

## Low / housekeeping

- **CancellationToken:** None of the actions accept `CancellationToken` or pass it to EF. Add a `CancellationToken ct` parameter to each action and thread it through.
- **Magic values:** The strings `"Pending"`, `"Cancelled"` and `"Perishable"`, and the numbers `50`, `500`, `1000` and `0.9m`, should be enums, constants or options.
- **Dead code:** `IReportService` is registered but no controller uses it. Remove it or wire it up.
- **Logging:** The project has no structured logging around authorization failures, stock changes or order cancellations. Inventory and price changes in particular should have an audit trail.
- **`Search` parameter:** `term` is a required non-nullable string. Missing values get an automatic 400 from `[ApiController]`, but validate the length too, for example `[StringLength(100, MinimumLength = 2)]`.
- **Tests:** There are no unit or integration tests. At minimum, add `WebApplicationFactory` tests for the authorization rules (#2, #3, #5, #6, #7) and for the restock business rules (#12, #13).

---

## Recommended fix order before deployment

1. Fix #5 (middleware order), #4 (move and rotate the signing key) and #1 (SQL injection).
2. Lock down `UsersController` (#2, #3, #21) and add ownership and role checks (#6, #7).
3. Fix order cancellation (#8, #9, #15) and `/orders/mine` (#10, #11).
4. Fix restock concurrency and pricing logic (#12, #13).
5. Add migrations and schema constraints (#19), the `HttpClient` factory (#14), and the production middleware (#20).
6. Add the auth and business-rule tests above. Then re-review.
