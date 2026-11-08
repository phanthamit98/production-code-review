# Code Review: InventoryApi (pre-production)

**Scope:** The whole project in `InventoryApi/`: `Program.cs`, `InventoryApi.csproj`, `Controllers/` (Products, Orders, Users), `Services/` (OrderService, ReportService), `Data/AppDbContext.cs`, `Models/Entities.cs`, `Dtos/ProductDtos.cs`. There are no tests, migrations, `appsettings*.json` or deployment config in the repo, so those were not reviewed. The code was read but not compiled or run.
**Stack:** ASP.NET Core 8 Web API (`net8.0`, `<Nullable>enable</Nullable>`), EF Core 8 SQL Server, JWT bearer auth.
**Verdict:** **Block**. Any logged-in user can run arbitrary SQL, make themselves admin or take over any account. Anyone who has seen the repo can forge tokens. And because the middleware order is wrong, every protected endpoint returns 401 today.

## Summary

| Severity | Count |
|---|---|
| Critical | 3 |
| High | 4 |
| Medium | 6 |
| Low | 2 |

| # | Severity | Category | Location | Finding |
|---|---|---|---|---|
| 1 | Critical | Security | `InventoryApi/Controllers/ProductsController.cs:14-19` | SQL injection in `GET /api/products/search` through `FromSqlRaw` with an interpolated string |
| 2 | Critical | Security | `InventoryApi/Controllers/UsersController.cs:20-28` | `PUT /api/users/{id}` binds the `User` entity: privilege escalation and account takeover |
| 3 | Critical | Security | `InventoryApi/Program.cs:24-25` | JWT signing key is hardcoded in source |
| 4 | High | Correctness / Security | `InventoryApi/Program.cs:37-38` | `UseAuthorization()` runs before `UseAuthentication()`, so every `[Authorize]` endpoint returns 401 |
| 5 | High | Security | `InventoryApi/Controllers/UsersController.cs:13-18` | `GET /api/users/{id}` returns any user's `PasswordHash` and `IsAdmin` (IDOR plus data exposure) |
| 6 | High | Security | `InventoryApi/Controllers/OrdersController.cs:13-18`, `InventoryApi/Services/OrderService.cs:16-17` | IDOR: any user can read any order |
| 7 | High | Security | `InventoryApi/Controllers/ProductsController.cs:54-74` | Any authenticated user can restock products and trigger price cuts (no role check) |
| 8 | Medium | Correctness | `InventoryApi/Services/OrderService.cs:32-42` | `SaveChangesAsync` failure is swallowed and the endpoint returns 204 "cancelled" |
| 9 | Medium | Correctness | `InventoryApi/Services/OrderService.cs:41,45-49` | `async void NotifyCancellation`: fire-and-forget that can crash the process |
| 10 | Medium | Correctness / Performance | `InventoryApi/Controllers/OrdersController.cs:20-26` | `.Result` blocks a thread-pool thread in `GET /api/orders/mine` |
| 11 | Medium | Performance | `InventoryApi/Services/OrderService.cs:19-25` | `GetForUserAsync` loads the whole `Orders` table and filters in memory |
| 12 | Medium | Correctness / Architecture | `InventoryApi/Controllers/ProductsController.cs:54-74` | Restock business rules live in the controller; the discount compounds on every restock; lost updates under concurrency |
| 13 | Medium | Performance | `InventoryApi/Services/ReportService.cs:16` | `new HttpClient()` per call (socket exhaustion) |
| 14 | Low | Type safety / Correctness | `InventoryApi/Controllers/OrdersController.cs:23,31` | `int.Parse(...FindFirstValue(...)!)` throws a 500 if the claim is missing or malformed |
| 15 | Low | Maintainability / Performance | several | Grouped hygiene items: unbounded lists, no `CancellationToken`, magic strings, decimal precision |

## Findings

### 1. SQL injection in product search

- **Location:** `InventoryApi/Controllers/ProductsController.cs:14-19`
- **Severity:** Critical
- **Category:** Security
- **Confidence:** High

**Root cause:** `FromSqlRaw($"... LIKE '%{term}%'")` builds the SQL text with C# string interpolation *before* EF sees it. `FromSqlRaw` takes a plain string, so `term` goes into the query verbatim. Only `FromSqlInterpolated` and `FromSql` turn interpolation holes into parameters, as `ByCategory` on line 28 correctly does.

**Impact / trigger:** Any authenticated user (once #4 is fixed) can call `GET /api/products/search?term=x'; UPDATE Users SET IsAdmin=1 --` or `term=x' UNION SELECT Id, Email, PasswordHash, ... FROM Users --`. That lets them read or modify any table the app's SQL login can reach, including `Users.PasswordHash`.

**Fix:** Use LINQ. It is parameterized, and it matches the `List` action that already exists:

```csharp
[HttpGet("search")]
public async Task<ActionResult<IEnumerable<ProductResponse>>> Search([FromQuery] string term)
{
    var products = await db.Products
        .AsNoTracking()
        .Where(p => p.Name.Contains(term))
        .OrderBy(p => p.Name)
        .Take(50)
        .Select(p => new ProductResponse(p.Id, p.Name, p.Category, p.Price, p.Stock))
        .ToListAsync();

    return Ok(products);
}
```

(If raw SQL is truly needed: `FromSql($"SELECT * FROM Products WHERE Name LIKE {"%" + term + "%"}")`.)

### 2. `PUT /api/users/{id}` binds the EF entity: privilege escalation and account takeover

- **Location:** `InventoryApi/Controllers/UsersController.cs:20-28`
- **Severity:** Critical
- **Category:** Security
- **Confidence:** High

**Root cause:** The action binds the `User` entity straight from the request body and calls `db.Users.Update(user)`, which marks *every* property as modified. That includes `IsAdmin`, `PasswordHash` and `Email`. The only check is that the route id matches the body id. Nothing checks that the caller is that user, or an admin.

**Impact / trigger:** Any authenticated user sends `PUT /api/users/7` with `{"id":7,"email":"me@evil.com","displayName":"x","passwordHash":"<hash I know>","isAdmin":true}`. They can make themselves admin, or overwrite another user's email and password hash to take over that account. Fields left out of the body are written back as defaults, so a normal profile update also wipes `PasswordHash` and `IsAdmin`.

**Fix:** Bind a DTO that contains only the editable fields, check that the caller owns the record, and map the fields explicitly:

```csharp
// Dtos/UserDtos.cs
public class UpdateUserRequest
{
    [Required, StringLength(100)]
    public string DisplayName { get; set; } = string.Empty;
}
public record UserResponse(int Id, string Email, string DisplayName);

// UsersController
[HttpPut("{id:int}")]
public async Task<IActionResult> Update(int id, UpdateUserRequest request)
{
    var callerId = int.Parse(User.FindFirstValue(ClaimTypes.NameIdentifier)!);
    if (callerId != id) return NotFound(); // or Forbid(); admins via a separate, role-protected endpoint

    var user = await db.Users.FindAsync(id);
    if (user is null) return NotFound();

    user.DisplayName = request.DisplayName;   // only allowed fields
    await db.SaveChangesAsync();
    return NoContent();
}
```

Email, password and admin changes should get their own flows: re-authentication for email and password, and an `[Authorize(Roles = "Admin")]` endpoint for admin rights.

### 3. JWT signing key is hardcoded in source

- **Location:** `InventoryApi/Program.cs:24-25`
- **Severity:** Critical
- **Category:** Security
- **Confidence:** High

**Root cause:** The symmetric signing key `"inventory-super-secret-signing-key-2024!!"` is a literal in source control. Anyone with the key can mint a valid token.

**Impact / trigger:** Anyone who has ever had read access to this repo can mint a token with `iss=inventory-api`, `aud=inventory-clients` and any `sub`/`nameidentifier`. That includes former staff, contractors, CI logs and a leaked clone. With such a token they can act as any user in production. Rotating the key would also require a code change and a redeploy.

**Fix:** Load the key from configuration (environment variable, user-secrets in development, Key Vault or a secret store in production). Fail at startup if it is missing, and rotate the current key because it is already compromised.

```csharp
var jwtKey = builder.Configuration["Jwt:SigningKey"]
    ?? throw new InvalidOperationException("Jwt:SigningKey is not configured.");

options.TokenValidationParameters = new TokenValidationParameters
{
    ValidateIssuer = true,
    ValidIssuer = builder.Configuration["Jwt:Issuer"],
    ValidateAudience = true,
    ValidAudience = builder.Configuration["Jwt:Audience"],
    ValidateLifetime = true,
    ValidateIssuerSigningKey = true,
    IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(jwtKey))
};
```

### 4. Authorization middleware runs before authentication

- **Location:** `InventoryApi/Program.cs:37-38`
- **Severity:** High
- **Category:** Correctness / Security
- **Confidence:** High

**Root cause:** `app.UseAuthorization()` is registered before `app.UseAuthentication()`. When the authorization middleware evaluates `[Authorize]`, the JWT has not yet been read, so `HttpContext.User` is anonymous. The default policy names no authentication scheme, so `PolicyEvaluator` does not authenticate on its own; it just sees an unauthenticated user and challenges. Because `UseAuthentication()` is called explicitly, `WebApplication` does not add its own copy earlier in the pipeline.

**Impact / trigger:** This fails *closed*. Every endpoint in all three controllers (all have class-level `[Authorize]`) returns 401, even with a valid token, so the API does not work in production. The danger is the obvious "quick fix" of removing `[Authorize]` or adding `[AllowAnonymous]` to make it work. Note also that findings #1, #2 and #5 to #7 become exploitable the moment this order is corrected, so fix them together.

**Fix:**

```csharp
app.UseHttpsRedirection();
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers();
```

### 5. `GET /api/users/{id}` exposes any user's password hash and admin flag

- **Location:** `InventoryApi/Controllers/UsersController.cs:13-18`
- **Severity:** High
- **Category:** Security
- **Confidence:** High

**Root cause:** The action returns the `User` entity as-is (`ActionResult<User>`), so `PasswordHash` and `IsAdmin` are serialized. It also loads the record by id with no check that the caller is that user (IDOR).

**Impact / trigger:** Any authenticated user can loop over `GET /api/users/1..N` and collect every user's email and password hash for offline cracking. They also learn which accounts are admins.

**Fix:** Return a response DTO and restrict access to the caller (or to admins):

```csharp
[HttpGet("{id:int}")]
public async Task<ActionResult<UserResponse>> Get(int id)
{
    var callerId = int.Parse(User.FindFirstValue(ClaimTypes.NameIdentifier)!);
    if (callerId != id && !User.IsInRole("Admin")) return NotFound();

    var user = await db.Users.AsNoTracking()
        .Where(u => u.Id == id)
        .Select(u => new UserResponse(u.Id, u.Email, u.DisplayName))
        .FirstOrDefaultAsync();

    return user is null ? NotFound() : Ok(user);
}
```

### 6. IDOR: any user can read any order

- **Location:** `InventoryApi/Controllers/OrdersController.cs:13-18`, `InventoryApi/Services/OrderService.cs:16-17`
- **Severity:** High
- **Category:** Security
- **Confidence:** High

**Root cause:** `GetByIdAsync(id)` filters only by `Id`. Neither the controller nor the service checks `Order.UserId` against the caller. `CancelAsync` (line 29) does filter by owner, so the pattern exists in the code but this method doesn't use it.

**Impact / trigger:** User A calls `GET /api/orders/1`, `/2`, ... and reads every customer's orders: totals, status, timestamps and owner `UserId`.

**Fix:** Scope the query to the owner, the same way `CancelAsync` already does:

```csharp
// IOrderService
Task<Order?> GetByIdAsync(int id, int userId);

// OrderService
public Task<Order?> GetByIdAsync(int id, int userId) =>
    db.Orders.AsNoTracking().FirstOrDefaultAsync(o => o.Id == id && o.UserId == userId);

// OrdersController
[HttpGet("{id:int}")]
public async Task<IActionResult> Get(int id)
{
    var userId = int.Parse(User.FindFirstValue(ClaimTypes.NameIdentifier)!);
    var order = await orders.GetByIdAsync(id, userId);
    return order is null ? NotFound() : Ok(order);
}
```

### 7. Any authenticated user can restock products and cut prices

- **Location:** `InventoryApi/Controllers/ProductsController.cs:54-74`
- **Severity:** High
- **Category:** Security
- **Confidence:** Medium (assumes restocking is meant to be a staff or admin operation; the `User.IsAdmin` field suggests roles exist, but no role or policy is used anywhere)

**Root cause:** `POST /api/products/{id}/restock` is protected only by the class-level `[Authorize]`, which means "any valid token". The action changes inventory and, through the discount rule, lowers `Price`.

**Impact / trigger:** Any customer account calls `POST /api/products/5/restock {"quantity":10000}` over and over. Stock grows without limit (no physical stock arrived), and each call above 1,000 units cuts the price by another 10% (see #12). The price soon approaches 0.

**Fix:** Require a role or policy. Issue the role claim when the token is created (based on `IsAdmin`):

```csharp
// Program.cs
builder.Services.AddAuthorizationBuilder()
    .AddPolicy("InventoryManager", p => p.RequireRole("Admin"));

// ProductsController
[HttpPost("{id:int}/restock")]
[Authorize(Policy = "InventoryManager")]
public async Task<IActionResult> Restock(int id, RestockRequest request) { ... }
```

### 8. Cancellation failure is swallowed and reported as success

- **Location:** `InventoryApi/Services/OrderService.cs:32-42`
- **Severity:** Medium
- **Category:** Correctness
- **Confidence:** High

**Root cause:** `catch (Exception) { }` discards any `SaveChangesAsync` failure (DB outage, deadlock, constraint error). The method then sends the notification and returns `true`, and the controller returns 204.

**Impact / trigger:** On any transient DB error the client and the user are told the order was cancelled, and a notification goes out, but the row still says `Pending`. Nothing is logged, so nobody can diagnose it later.

**Fix:** Let the exception propagate (a global exception handler turns it into a 500), or log it and return failure:

```csharp
order.Status = "Cancelled";
await db.SaveChangesAsync();   // no try/catch: failure must not look like success
await NotifyCancellationAsync(order.Id);
return true;
```

### 9. `async void` fire-and-forget notification

- **Location:** `InventoryApi/Services/OrderService.cs:41`, `InventoryApi/Services/OrderService.cs:45-49`
- **Severity:** Medium
- **Category:** Correctness
- **Confidence:** High

**Root cause:** `async void` cannot be awaited. An exception thrown inside it goes to the synchronization context or thread pool and terminates the process. The work also continues after the request, and the scoped `logger`/service, may be disposed by then. Today the method only logs, but as soon as real notification code (email, HTTP) goes in, a single failure crashes the API.

**Fix:** Make it `Task`-returning and await it. If it really must run in the background, enqueue it to a hosted `BackgroundService` through a `Channel<T>`:

```csharp
private async Task NotifyCancellationAsync(int orderId)
{
    // real notification here
    logger.LogInformation("Order {OrderId} cancellation notification sent", orderId);
}
```

### 10. Sync-over-async `.Result` in `GET /api/orders/mine`

- **Location:** `InventoryApi/Controllers/OrdersController.cs:20-26`
- **Severity:** Medium
- **Category:** Correctness / Performance
- **Confidence:** High

**Root cause:** `orders.GetForUserAsync(userId).Result` blocks a thread-pool thread for the whole DB round-trip. Exceptions also arrive wrapped in `AggregateException`.

**Impact / trigger:** Under load this causes thread-pool starvation and latency spikes across the whole API. It is worse here because of the full-table load in #11.

**Fix:**

```csharp
[HttpGet("mine")]
public async Task<IActionResult> Mine()
{
    var userId = int.Parse(User.FindFirstValue(ClaimTypes.NameIdentifier)!);
    return Ok(await orders.GetForUserAsync(userId));
}
```

### 11. `GetForUserAsync` loads every order in the database

- **Location:** `InventoryApi/Services/OrderService.cs:19-25`
- **Severity:** Medium
- **Category:** Performance
- **Confidence:** High

**Root cause:** `ToListAsync()` runs before `.Where(o => o.UserId == userId)`, so EF fetches the entire `Orders` table and filters and sorts in memory.

**Impact / trigger:** Every call to `/api/orders/mine` reads all orders from all customers. Memory use, DB I/O and latency grow with total order volume, not with the caller's order count.

**Fix:** Filter, sort and page in the database:

```csharp
public Task<List<Order>> GetForUserAsync(int userId, int page = 1, int pageSize = 50) =>
    db.Orders.AsNoTracking()
        .Where(o => o.UserId == userId)
        .OrderByDescending(o => o.CreatedAt)
        .Skip((Math.Max(page, 1) - 1) * pageSize)
        .Take(pageSize)
        .ToListAsync();
```

### 12. Restock rules in the controller: compounding discount, lost updates

- **Location:** `InventoryApi/Controllers/ProductsController.cs:54-74`
- **Severity:** Medium
- **Category:** Correctness / Architecture
- **Confidence:** High

**Root cause:** The perishable cap (500), the discount threshold (1000) and the 10% price cut are business rules written inline in the controller with magic numbers. Three problems follow:
- The discount runs on *every* restock that leaves stock above 1,000, so the price compounds down: 100 → 90 → 81 → … after repeated small restocks.
- The read-modify-write of `Stock` has no concurrency token, so two concurrent restocks can lose one increment.
- The rules can't be unit-tested or reused, unlike order logic, which already lives in `OrderService`.

**Fix:** Move the logic into an `IProductService` (same pattern as `IOrderService`). Apply the discount only when the threshold is first crossed, or better, store a discount separately instead of overwriting `Price`. Add a concurrency token:

```csharp
// Product
[Timestamp] public byte[] RowVersion { get; set; } = [];

// ProductService.RestockAsync
var wasBelow = product.Stock <= DiscountThreshold;
product.Stock += quantity;
if (wasBelow && product.Stock > DiscountThreshold)
    product.Price = Math.Round(product.Price * BulkDiscountFactor, 2);
await db.SaveChangesAsync(); // catch DbUpdateConcurrencyException → retry or 409
```

### 13. `new HttpClient()` per call

- **Location:** `InventoryApi/Services/ReportService.cs:16`
- **Severity:** Medium
- **Category:** Performance
- **Confidence:** Medium (the service is registered in DI but has no caller in the reviewed code, so the impact appears once it is wired up)

**Root cause:** Creating and disposing an `HttpClient` on every call leaves sockets in `TIME_WAIT` and can exhaust ports under load. It also ignores DNS changes and has no timeout or resilience configuration.

**Fix:** Use a typed client through `IHttpClientFactory`:

```csharp
// Program.cs
builder.Services.AddHttpClient<IReportService, ReportService>(c =>
{
    c.BaseAddress = new Uri(builder.Configuration["Rates:BaseUrl"]
        ?? throw new InvalidOperationException("Rates:BaseUrl is not configured."));
    c.Timeout = TimeSpan.FromSeconds(10);
});

// ReportService
public class ReportService(HttpClient client) : IReportService
{
    public async Task<decimal> GetExchangeRateAsync(string currency, CancellationToken ct)
    {
        var response = await client.GetFromJsonAsync<RateResponse>(
            $"rates/{Uri.EscapeDataString(currency)}", ct);
        return response?.Rate ?? throw new InvalidOperationException($"No rate returned for {currency}.");
    }
}
```

(Remove the existing `AddScoped<IReportService, ReportService>()` registration.)

### 14. Claim parsing with null-forgiving `!` and `int.Parse`

- **Location:** `InventoryApi/Controllers/OrdersController.cs:23`, `InventoryApi/Controllers/OrdersController.cs:31`
- **Severity:** Low
- **Category:** Type safety / Correctness
- **Confidence:** High

`int.Parse(User.FindFirstValue(ClaimTypes.NameIdentifier)!)` throws, and returns a 500, for a token without a numeric `sub`/`nameidentifier`. Move this into one helper (for example a `ClaimsPrincipal.GetUserId()` extension using `int.TryParse` and returning `Unauthorized()` on failure) and reuse it in the new ownership checks from #2, #5 and #6.

### 15. Grouped hygiene items

- **Location:** several (listed below)
- **Severity:** Low
- **Category:** Maintainability / Performance
- **Confidence:** High

- `ProductsController.Search` and `ByCategory` (`:14-33`) return unbounded result sets. Add `Take` or paging like `List` does. `Search` also lacks `AsNoTracking()`.
- No action takes or passes a `CancellationToken`. Add a `CancellationToken ct` parameter and pass it to `ToListAsync`, `FindAsync` and `SaveChangesAsync`.
- `Order.Status` uses magic strings (`"Pending"`, `"Cancelled"`, `Models/Entities.cs:17`, `OrderService.cs:32`). Use an enum.
- `OrdersController` returns the `Order` entity directly. It has no sensitive fields today, but returning a response DTO (as `ProductResponse` does) keeps future columns from leaking.
- `Product.Price` and `Order.Total` have no configured decimal precision, so EF Core warns and defaults to `decimal(18,2)`. Set `[Precision(18, 2)]` or configure it in `OnModelCreating` explicitly.

## What's done well

- `ByCategory` uses `FromSqlInterpolated`, which is correctly parameterized and shows the safe raw-SQL pattern to copy.
- `List` is a good model for read endpoints: LINQ filter, `AsNoTracking()`, server-side paging with a clamped page number, and projection to `ProductResponse` in SQL.
- `CancelAsync` scopes the lookup by `UserId`, the correct ownership check, which just needs applying to `GetByIdAsync`.
- `RestockRequest` uses `[Range]` with `[ApiController]`, so invalid quantities get an automatic 400.
- Nullable reference types are enabled, all controllers have class-level `[Authorize]`, the JWT validates issuer, audience and lifetime, and the connection string comes from configuration rather than source.

## Notes

- The code was reviewed statically; it was not built or run. Finding #4 is based on ASP.NET Core 8 middleware behavior (the default policy has no authentication schemes, and an explicit `UseAuthentication()` stops `WebApplication` from adding its own). Confirm it with one request carrying a valid token before and after the fix.
- No token-issuing endpoint exists in this project, so it is assumed that tokens are issued elsewhere with the same hardcoded key (#3). If so, that service needs the same key-management fix, and it should put a role claim in the token for #7.
- Production hardening that isn't a bug in this code, but is worth adding before go-live: `app.UseExceptionHandler()` with ProblemDetails (#8 depends on it), HSTS, health checks, and rate limiting on `search`.
- Not reviewed, because they are not in the repo: `appsettings*.json`, EF migrations and the database schema, the tests, and CI/CD or hosting configuration.
