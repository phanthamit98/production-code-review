# Severity Rubric and Verification Guide

## Severity

Judge impact × likelihood **in this codebase**, not the category in the abstract.

| Severity | Meaning | Typical examples | Merge? |
|---|---|---|---|
| **Critical** | Exploitable now by an outside or low-privilege user; data breach, takeover, money loss | SQL injection on a reachable endpoint; privilege escalation via mass assignment; secret shipped to browser; unauthenticated write endpoint | Block |
| **High** | Serious security or data-integrity problem that needs a specific condition, or a bug that will break a main flow | IDOR; stored XSS; leaking password hashes; unverified webhook; client-controlled price; auth middleware order | Block |
| **Medium** | Real bug or design problem with limited blast radius, or one that will cause incidents under load | Swallowed errors; N+1; whole-table load; `async void`; blocking on async; business logic in handlers; HttpClient per call | Fix before or soon after merge |
| **Low** | Maintainability, minor type looseness, small inefficiencies | `any` in an internal helper; dead code; missing `AsNoTracking` | Optional |

Rules of thumb:
- If you can't name who could exploit it and how, it is not Critical.
- Architecture issues are Medium unless they directly cause a bug listed above.
- Group many Lows of the same kind into one finding.

## Confidence

- **High** — you traced the path and the problem is certain.
- **Medium** — very likely, but depends on code or config you can't see (say what).
- **Low** — worth a question; phrase the finding as a question to the author.

## Verification checklist (run for every candidate finding)

1. **Re-read** the exact lines plus ~20 lines around them.
2. **Look upward** for protection: middleware/matcher, class-level attributes, base controller, wrapper functions, global filters, the caller.
3. **Check the framework's default behavior** (see the "Not bugs" section of the stack reference).
4. **Build the trigger**: a concrete request, input or sequence that causes the problem. No trigger → drop it or downgrade to a Low-confidence question.
5. **Check you aren't double-reporting** the same root cause under two categories. Report once, under the most severe category, and mention the secondary effect.

## Common false positives

| Looks like | Why it's usually fine |
|---|---|
| Value rendered in JSX / Razor `@value` | Auto-escaped |
| Tagged-template or interpolated EF/Prisma raw query | Parameterized |
| Action without `[Authorize]` | Class-level `[Authorize]` applies |
| Route without session check | Covered by `middleware.ts` matcher |
| `process.env.X` in server code | Not exposed unless prefixed `NEXT_PUBLIC_` and used client-side |
| "No input validation" | DTO has data annotations with `[ApiController]`, or a zod schema parses it upstream |
