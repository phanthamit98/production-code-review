# Answer Key (เฉลยปัญหาที่ฝังไว้)

ไฟล์นี้อยู่นอกโฟลเดอร์ Skill โดยตั้งใจ เพื่อไม่ให้ AI ที่ถูกทดสอบเห็นเฉลย โปรเจคทดสอบไม่มี comment ที่ใบ้ถึงปัญหา

## Next.js — `evals/review-nextjs-shop/files` (13 ปัญหา + 4 decoy)

| # | ไฟล์ | ปัญหา | ระดับที่คาดหวัง |
|---|---|---|---|
| N1 | `app/api/orders/route.ts` | SQL injection: `status` ต่อ string เข้า `$queryRawUnsafe` | Critical |
| N2 | `app/api/orders/[id]/route.ts` | IDOR: `DELETE` ลบ order ของคนอื่นได้ (ไม่เช็ค `userId`) | High |
| N3 | `app/actions/profile.ts` | Server Action ไม่เช็ค auth, เชื่อ `userId` จาก argument, spread `formData` ทั้งก้อน → ตั้ง `role` เองได้ | Critical |
| N4 | `app/products/[slug]/page.tsx` | Stored XSS: `dangerouslySetInnerHTML` กับ `product.description` | High |
| N5 | `app/dashboard/page.tsx` | `useEffect` ไม่มี dependency array → fetch ทุก render | Medium |
| N6 | `lib/config.ts` + `app/dashboard/page.tsx` | Stripe secret key อยู่ใน `NEXT_PUBLIC_*` และถูก import เข้า client component | Critical |
| N7 | `app/api/webhooks/stripe/route.ts` | `catch {}` กลืน error แล้วตอบ 200 | Medium |
| N8 | `app/api/webhooks/stripe/route.ts` | ไม่ verify webhook signature → ปลอม event "จ่ายเงินแล้ว" ได้ | High–Critical |
| N9 | `app/api/users/route.ts` | ส่ง user ทั้ง record (รวม `passwordHash`) กลับไป | High |
| N10 | `app/api/users/route.ts` | ใช้ `any` | Low |
| N11 | `app/api/checkout/route.ts` | ใช้ `price` ที่ client ส่งมา → กำหนดราคาเองได้ | Critical–High |
| N12 | `app/api/checkout/route.ts` | Business logic (ค่าส่ง, VAT) อยู่ใน route handler | Medium |
| N13 | `app/api/checkout/route.ts` | N+1: `findUnique` ใน loop | Medium |
| D1 | `app/products/[slug]/page.tsx` | `{review.body}` ใน JSX — **ปลอดภัย** (React escape) | — |
| D2 | `app/api/reviews/route.ts` | `$queryRaw` tagged template — **ปลอดภัย** (parameterized) | — |
| D3 | `app/api/reviews/route.ts` | `process.env.STRIPE_SECRET_KEY` ฝั่ง server — **ปลอดภัย** | — |
| D4 | `app/actions/review.ts` | `createReview` มี auth + zod — **ปลอดภัย** | — |

## .NET — `evals/review-dotnet-inventory/files` (12 ปัญหา + 4 decoy)

| # | ไฟล์ | ปัญหา | ระดับที่คาดหวัง |
|---|---|---|---|
| T1 | `Program.cs` | `UseAuthorization()` ก่อน `UseAuthentication()` | High |
| T2 | `Program.cs` | JWT signing key hardcode ในโค้ด | High–Critical |
| T3 | `ProductsController.cs` `Search` | SQL injection ผ่าน `FromSqlRaw($"...{term}...")` | Critical |
| T4 | `ProductsController.cs` `Restock` | Business rule + DbContext ใน controller | Medium |
| T5 | `OrdersController.cs` `Get` | IDOR: ดู order ของคนอื่นได้ | High |
| T6 | `OrdersController.cs` `Mine` | `.Result` บล็อก async | Medium |
| T7 | `UsersController.cs` `Update` | Over-posting entity → ตั้ง `IsAdmin` เองได้ / แก้ user คนอื่นได้ | Critical |
| T8 | `UsersController.cs` `Get` | คืน entity รวม `PasswordHash` | High |
| T9 | `OrderService.cs` `CancelAsync` | `catch (Exception) {}` กลืน error แล้ว return true | Medium |
| T10 | `OrderService.cs` | `async void NotifyCancellation` | Medium |
| T11 | `OrderService.cs` `GetForUserAsync` | โหลดทั้งตารางแล้ว filter ใน memory | Medium |
| T12 | `ReportService.cs` | `new HttpClient()` ทุกครั้ง | Medium |
| DD1 | `ProductsController.cs` `ByCategory` | `FromSqlInterpolated` — **ปลอดภัย** | — |
| DD2 | `ProductsController.cs` `List` | LINQ `Contains` — **ปลอดภัย** | — |
| DD3 | ทุก controller | action ไม่มี `[Authorize]` แต่ class มี — **ปลอดภัย** | — |
| DD4 | `Dtos/ProductDtos.cs` | `RestockRequest` มี `[Range]` + `[ApiController]` — **มี validation แล้ว** | — |
