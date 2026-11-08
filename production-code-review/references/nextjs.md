# Next.js / React / TypeScript Specifics

Read after `core-checklist.md`. These are the stack-specific ways the core issues show up — and the stack-specific reasons something that *looks* wrong is actually fine.

## Entry points to trace

- `app/**/route.ts` — Route Handlers (`GET`, `POST`, ...). Each exported method is a public HTTP endpoint.
- Files or functions with `"use server"` — **Server Actions are public POST endpoints.** Anyone can call them with any arguments, regardless of which page renders the form. Each action needs its own auth check and input validation; hiding the button in the UI protects nothing.
- `pages/api/**` — legacy API routes.
- `middleware.ts` — check its `matcher`: it shows which paths are already guarded.
- Server Components that read `searchParams` / `params` and pass them to queries.

## Security

| Look for | Why it's a problem | Fix direction |
|---|---|---|
| `prisma.$queryRawUnsafe(...)`, `$executeRawUnsafe`, or raw SQL built with `+` / template strings passed to a driver | SQL injection | Prisma query API, or `$queryRaw` tagged template (parameterized) |
| `Object.fromEntries(formData)` / `...body` passed to `create`/`update` | Mass assignment (e.g. `role`) | Validate with a schema (zod) that lists allowed fields only |
| Server Action / Route Handler with no session check | Unauthenticated access | Check session at the top of each action/handler |
| `findUnique({ where: { id } })` then update/delete without comparing `userId` or role | IDOR | Include owner in the `where`, or check and return 403/404 |
| `dangerouslySetInnerHTML` with user/DB content | Stored XSS | Render as text, or sanitize (e.g. DOMPurify) with a strict allowlist |
| `NEXT_PUBLIC_*` holding a secret, or a secret imported into a `"use client"` module | Secret shipped to every browser | Keep secrets server-only (no `NEXT_PUBLIC_`), use `server-only` package |
| Returning Prisma entities directly (`return NextResponse.json(user)`) | Leaks `passwordHash`, tokens | `select` explicit fields or map to a DTO |
| Webhook handler that parses JSON without verifying the provider signature | Forged events | Verify signature with the raw body before trusting it |
| Prices/totals read from the request body | Client controls what they pay | Look up prices on the server |

## Correctness

- `useEffect` without a dependency array that sets state → runs after every render → infinite loop / request storm.
- `useEffect` with missing dependencies → stale data. Fetching in an effect where a Server Component would do.
- `try { ... } catch {}` or `catch (e) { console.log(e) }` followed by `return NextResponse.json({ ok: true })` → hides failures; webhooks then get acknowledged and never retried.
- Missing `await` on Prisma calls inside handlers.
- Not returning proper status codes (404 for missing, 400 for invalid input, 401/403 for auth).

## Architecture

- Business logic (pricing, permissions) inside `route.ts`, Server Actions or components → move to `lib/services/*` (or the project's existing equivalent). Handlers/actions should validate, authorize, delegate.
- Direct Prisma calls spread across components and handlers → data-access module.
- `"use client"` on components that don't need interactivity forces data fetching to the client.

## Performance

- `await prisma.x.findUnique()` inside a `for` loop → N+1; use `findMany({ where: { id: { in: ids } } })`.
- List endpoints with no `take`/pagination.
- Creating `new PrismaClient()` per request instead of the shared singleton.

## Type safety

- `any` on request bodies / action arguments; `as SomeType` on `await req.json()` without validation.
- `tsconfig.json` with `"strict": false` — mention once at project level.

## Not bugs (don't flag these)

- `{user.name}` or any value interpolated as JSX text — React escapes it.
- `prisma.$queryRaw\`... ${value}\`` (tagged template) — parameterized.
- `process.env.SECRET` (no `NEXT_PUBLIC_`) read in a Route Handler, Server Action, or Server Component — never sent to the browser.
- A route under a path that `middleware.ts` matcher protects lacking its own session check — it *is* authenticated. You may suggest defense-in-depth as Low, but not report it as missing auth.
- A Server Action that already calls the session helper and validates with zod.
