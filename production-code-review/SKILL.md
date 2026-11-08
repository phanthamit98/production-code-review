---
name: production-code-review
description: Stack-aware, evidence-based code review for Next.js (App Router, Route Handlers, Server Actions, React) and ASP.NET Core / .NET (Web API, EF Core) codebases. Finds security holes, broken authorization, swallowed errors, layering violations, type-safety gaps and performance traps, verifies each finding against the framework's real behavior to cut false positives, and produces a fixed-format report with file:line, severity, root cause and a concrete fix. Use this skill whenever the user asks to review, audit, check, or "look over" code, a PR, a diff, a branch, a folder or a whole project written in TypeScript/JavaScript/Next.js/React or C#/.NET — including phrasings like "is this safe to merge", "anything wrong with this", "security check my API", "รีวิวโค้ด", "ตรวจโค้ดให้หน่อย" — even if the user doesn't say the word "review".
---

# Production Code Review

Review code the way a careful senior engineer on the team would: understand how data flows before judging it, report only what is actually wrong, explain *why* it is wrong, and show how to fix it.

The two things that make an AI review useless are (1) missing the dangerous bug while listing twenty style nits, and (2) confidently flagging code that is actually safe because the framework already handles it. This workflow is built around avoiding both.

## Input

Accept any of these; ask only if none can be inferred:

| Input | How to get the code |
|---|---|
| A path (file or folder) | Read it directly |
| A diff / PR / branch | `git diff <base>...HEAD` (default base: `main`, fall back to `master`); review changed lines, but read enough surrounding code to judge them |
| Pasted code | Review as-is; state assumptions about the parts you can't see |

Optional: a focus (e.g. "security only"), the reader's language (write the report in the language the user wrote in), an output path.

## Workflow

### 1. Map the project (before judging anything)

Run the stack detector — it finds the stack and every entry point that receives external input:

```bash
python <skill-dir>/scripts/detect_stack.py <project-root>
```

Then read:
- Project conventions if present: `CLAUDE.md`, `README`, `.editorconfig`, `tsconfig.json` (is `strict` on?), `*.csproj` (`<Nullable>`), lint config.
- Cross-cutting protection: `middleware.ts`, auth helpers, `Program.cs` pipeline, global filters, class-level `[Authorize]`. You need to know what is already protected *before* you call something unprotected.

Load only the references that apply:
- Always: `references/core-checklist.md`
- Next.js / React / TypeScript: `references/nextjs.md`
- .NET / C#: `references/dotnet.md`
- Before assigning severities: `references/severity-and-verification.md`

### 2. Trace untrusted input

For each entry point (route handler, Server Action, API route, controller action, webhook, minimal API), follow the data: where does it enter → is it validated → is the caller authenticated → is the caller *authorized for this specific record* → where does it end up (SQL, HTML, filesystem, outbound HTTP, response body)?

Most Critical and High findings live on these paths. Doing this first means you spend attention where the risk is, instead of reading files alphabetically.

### 3. Review in passes

Go through the code once per category from the core checklist, in this order: **Security → Correctness & error handling → Architecture/layering → Type safety → Performance → Maintainability**. One category at a time catches more than "reading for everything at once", because each pass asks a different question of the same line.

### 4. Verify every finding (the false-positive filter)

Before writing a finding down, prove it. For each candidate:

1. Re-read the exact lines and the code around them.
2. Ask: *does the framework, a middleware, a base class, or a caller already handle this?* (Examples that are NOT bugs: `{value}` in JSX is escaped; Prisma `$queryRaw` tagged templates and EF `FromSqlInterpolated`/LINQ are parameterized; a class-level `[Authorize]` covers every action without `[AllowAnonymous]`; a non-`NEXT_PUBLIC_` env var read on the server never reaches the browser.) `references/severity-and-verification.md` lists more.
3. Can you describe a concrete input or sequence that triggers the problem? If you can't, either drop it or report it as a question with `Confidence: Low`.

A short report that is all true is worth far more than a long one the reader has to second-guess.

### 5. Assign severity

Use the rubric in `references/severity-and-verification.md`. Severity reflects impact × likelihood in *this* code, not how scary the category sounds.

### 6. Write the report

Use the template in `assets/report-template.md` exactly. Rules that keep it useful:

- Every finding has `file:line` (or a line range), category, severity, confidence.
- Explain the **root cause** first, then the fix. Give a code fix for every Critical and High; a one-line description is enough for Low.
- Fixes must fit the existing architecture and conventions (e.g. move logic into the existing service layer, use the validation library the project already uses). Don't introduce a new library to fix one bug.
- Don't report what a formatter or linter would fix automatically (quotes, semicolons, import order). Group repetitive Low findings into one entry, but still list every `file:line` inside it — "several places" forces the author to hunt for them.
- Include "What's done well" only when it's specific and true — it tells the author which patterns to keep.
- End with a verdict: **Block**, **Approve with changes**, or **Approve**, with the one-sentence reason.

Save the report to `code-review-report.md` in the project root (or the path the user asked for) and give the user the summary table plus the verdict in chat.

## Scope and honesty

- If the code is too large to review fully, say what you covered and what you didn't, and prioritize entry points and changed files.
- If you could not run or compile the code, say so; don't imply findings were tested.
- Never invent line numbers. If the input has no line numbers (pasted snippet), reference the function name instead.
