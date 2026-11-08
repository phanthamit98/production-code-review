# Code Review: shop-admin (Next.js)

**Scope:** ทั้งโปรเจค: `app/actions/*`, `app/api/**/route.ts` (7 ไฟล์), `app/products/[slug]/page.tsx`, `app/dashboard/page.tsx`, `lib/*`, `package.json`, `tsconfig.json`. **ไม่ได้รีวิว:** `@/auth` (ไฟล์ config ของ next-auth ไม่มีในโปรเจคที่ส่งมา), Prisma schema (`schema.prisma` ไม่มี), และไม่มี `middleware.ts` ในโปรเจค ไม่ได้รันหรือ build โค้ด ทุก finding มาจากการอ่านโค้ด
**Stack:** Next.js 15.1 (App Router, Route Handlers, Server Actions), React 19, Prisma 6.1, next-auth 5 beta, Stripe 17, zod 3, TypeScript 5.7 (`strict: true`)
**Verdict:** **Block** — มีช่องโหว่ระดับ Critical 4 จุดที่คนนอกหรือผู้ใช้ทั่วไปโจมตีได้ทันที (SQL injection, ยึดสิทธิ์ admin ผ่าน `updateProfile`, Stripe secret key หลุดไปที่ browser, webhook ปลอมให้ order เป็น PAID ได้)

## Summary

| Severity | Count |
|---|---|
| Critical | 4 |
| High | 5 |
| Medium | 2 |
| Low | 2 |

| # | Severity | Category | Location | Finding |
|---|---|---|---|---|
| 1 | Critical | Security | `app/api/orders/route.ts:11-15` | SQL injection ผ่าน `status` ใน `$queryRawUnsafe` |
| 2 | Critical | Security | `app/actions/profile.ts:6-12` | `updateProfile` ไม่มี auth, รับ `userId` จาก client และ mass assignment (`role`) |
| 3 | Critical | Security | `lib/config.ts:4`, `app/dashboard/page.tsx:4` | Stripe secret key ใช้ `NEXT_PUBLIC_` และถูก import ใน client component |
| 4 | Critical | Security | `app/api/webhooks/stripe/route.ts:4-15` | Webhook ไม่ตรวจ signature + กลืน error ทั้งหมด |
| 5 | High | Security | `app/api/checkout/route.ts:13-37` | ราคาและจำนวนสินค้ามาจาก client โดยไม่ validate |
| 6 | High | Security | `app/api/orders/[id]/route.ts:27-28` | IDOR: ลบ order ของคนอื่นได้ |
| 7 | High | Security | `app/products/[slug]/page.tsx:18` | Stored XSS ผ่าน `dangerouslySetInnerHTML` |
| 8 | High | Security | `app/api/users/route.ts:11-13` | ส่ง User entity ทั้งก้อน (รวม password hash) กลับไป |
| 9 | High | Correctness | `app/dashboard/page.tsx:12-17` | `useEffect` ไม่มี dependency array ทำให้ fetch วนไม่สิ้นสุด |
| 10 | Medium | Performance / Correctness | `app/api/checkout/route.ts:19-40` | N+1 query และไม่มี transaction / ไม่ตัด stock |
| 11 | Medium | Architecture | `app/api/checkout/route.ts:18-29` | Business logic (ราคา, ค่าส่ง, VAT) อยู่ใน route handler |
| 12 | Low | Correctness | `app/actions/review.ts:26` | `revalidatePath` ใช้ `productId` แต่ route ใช้ `slug` |
| 13 | Low | Type safety / Performance | หลายไฟล์ | รวม Low: cast ไม่ตรวจสอบ, `any`, list ไม่มี pagination, เรียก Stripe ทุก request |

## Findings

### 1. SQL injection ใน `GET /api/orders`

- **Location:** `app/api/orders/route.ts:11-15`
- **Severity:** Critical
- **Category:** Security
- **Confidence:** High

**Root cause:** ค่า `status` จาก query string ถูกต่อ string เข้าไปใน SQL แล้วส่งให้ `db.$queryRawUnsafe` ซึ่งไม่ทำ parameterization ใด ๆ (ต่างจาก `$queryRaw` แบบ tagged template)

**Impact / trigger:** ผู้ใช้ที่ login แล้วคนไหนก็ได้เรียก `GET /api/orders?status=x' OR '1'='1` จะเห็น order ของทุกคน หรือใช้ `UNION SELECT` ดึงตาราง `User` (email, password hash) ออกมาได้ทั้งตาราง

**Fix:** ใช้ Prisma query API และ validate `status` ด้วย zod (โปรเจคใช้อยู่แล้ว)

```ts
import { z } from "zod";

const querySchema = z.object({
  status: z.enum(["PENDING", "PAID", "CANCELLED"]).default("PENDING"), // ปรับตาม enum ใน schema
});

export async function GET(req: NextRequest) {
  const user = await getSessionUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const parsed = querySchema.safeParse({
    status: req.nextUrl.searchParams.get("status") ?? undefined,
  });
  if (!parsed.success) return NextResponse.json({ error: "Invalid status" }, { status: 400 });

  const orders = await db.order.findMany({
    where: { userId: user.id, status: parsed.data.status },
    select: { id: true, total: true, status: true, createdAt: true },
    orderBy: { createdAt: "desc" },
    take: 50,
  });
  return NextResponse.json(orders);
}
```

### 2. `updateProfile` ไม่มี auth, เชื่อ `userId` จาก client และ mass assignment

- **Location:** `app/actions/profile.ts:6-12`
- **Severity:** Critical
- **Category:** Security
- **Confidence:** High

**Root cause:** Server Action คือ public POST endpoint ใครก็เรียกได้ด้วย argument อะไรก็ได้ action นี้ (1) ไม่เช็ค session (2) รับ `userId` เป็น argument จาก client และ (3) เอา `Object.fromEntries(formData)` ใส่ใน `db.user.update` ตรง ๆ โดยไม่จำกัด field ไม่มี `middleware.ts` ในโปรเจคที่จะกันไว้ให้

**Impact / trigger:** คนที่ไม่ได้ login ก็เรียก action นี้ได้ ส่ง `userId` ของตัวเองพร้อม form field `role=ADMIN` ก็กลายเป็น admin ได้ทันที หรือส่ง `userId` ของคนอื่นแล้วเปลี่ยน `email` เพื่อยึดบัญชี

**Fix:** เอา `userId` จาก session เท่านั้น และ whitelist field ด้วย zod (แบบเดียวกับ `app/actions/review.ts`)

```ts
"use server";

import { z } from "zod";
import { revalidatePath } from "next/cache";
import { db } from "@/lib/db";
import { getSessionUser } from "@/lib/auth";

const profileSchema = z.object({
  name: z.string().trim().min(1).max(100),
  // เพิ่มเฉพาะ field ที่ผู้ใช้แก้เองได้ ห้ามมี role / email / balance
});

export async function updateProfile(formData: FormData) {
  const user = await getSessionUser();
  if (!user) return { error: "Please sign in." };

  const parsed = profileSchema.safeParse(Object.fromEntries(formData));
  if (!parsed.success) return { error: "Invalid profile." };

  await db.user.update({ where: { id: user.id }, data: parsed.data });
  revalidatePath("/profile");
  return { ok: true };
}
```

### 3. Stripe secret key ถูกส่งไปที่ browser

- **Location:** `lib/config.ts:4`, `app/dashboard/page.tsx:4`
- **Severity:** Critical
- **Category:** Security
- **Confidence:** High

**Root cause:** ตัวแปร `NEXT_PUBLIC_STRIPE_SECRET_KEY` มี prefix `NEXT_PUBLIC_` ซึ่ง Next.js จะ inline ค่าเข้า JS bundle ตอน build และ `lib/config.ts` ยังถูก import โดย `app/dashboard/page.tsx` ที่เป็น `"use client"` ทำให้ object `config` ทั้งก้อน (รวม secret key) ไปอยู่ใน client bundle

**Impact / trigger:** ใครก็ตามที่เปิดหน้า `/dashboard` แล้วดู JS bundle จะได้ Stripe secret key ไปใช้สร้าง refund, ดูข้อมูลลูกค้า, หรือยิง API ในนามร้านได้ทั้งหมด

**Fix:** ลบ secret ออกจาก config ที่ client ใช้, ใช้ env ที่ไม่มี `NEXT_PUBLIC_` (`app/api/reviews/route.ts` ใช้ `process.env.STRIPE_SECRET_KEY` ถูกแล้ว) และแยก module ฝั่ง server ด้วย `server-only` **หมุน (rotate) key ใน Stripe dashboard ทันที** หากเคย deploy ไปแล้ว

```ts
// lib/config.ts (ใช้ได้ทั้ง client/server — ห้ามมี secret)
export const config = {
  appName: "Shop Admin",
  stripePublishableKey: process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY ?? "",
  currency: "thb",
};

// lib/stripe.ts (server only)
import "server-only";
import Stripe from "stripe";
export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);
```

### 4. Stripe webhook ไม่ตรวจ signature และกลืน error

- **Location:** `app/api/webhooks/stripe/route.ts:4-15`
- **Severity:** Critical
- **Category:** Security (ผลรอง: Correctness)
- **Confidence:** High

**Root cause:** handler เชื่อ `await req.json()` ทันทีโดยไม่ verify `stripe-signature` และมี `catch (err) {}` ว่างเปล่า แล้วตอบ `200 { received: true }` ทุกกรณี

**Impact / trigger:** ใครก็ได้ (ไม่ต้อง login) ยิง `POST /api/webhooks/stripe` ด้วย body `{"type":"checkout.session.completed","data":{"object":{"metadata":{"orderId":"<id>"}}}}` order นั้นจะถูกเปลี่ยนเป็น `PAID` โดยไม่ได้จ่ายเงินจริง (ได้ของฟรี) ผลรอง: เมื่อ DB update ล้มเหลว Stripe จะได้ 200 และไม่ retry อีก ทำให้ order ที่จ่ายจริงค้างเป็น `PENDING` โดยไม่มี log

**Fix:**

```ts
import { NextRequest, NextResponse } from "next/server";
import Stripe from "stripe";
import { stripe } from "@/lib/stripe";
import { db } from "@/lib/db";

export async function POST(req: NextRequest) {
  const signature = req.headers.get("stripe-signature");
  if (!signature) return NextResponse.json({ error: "Missing signature" }, { status: 400 });

  let event: Stripe.Event;
  try {
    const rawBody = await req.text();
    event = stripe.webhooks.constructEvent(rawBody, signature, process.env.STRIPE_WEBHOOK_SECRET!);
  } catch {
    return NextResponse.json({ error: "Invalid signature" }, { status: 400 });
  }

  try {
    if (event.type === "checkout.session.completed") {
      const session = event.data.object as Stripe.Checkout.Session;
      const orderId = session.metadata?.orderId;
      if (orderId) {
        await db.order.update({ where: { id: orderId }, data: { status: "PAID" } });
      }
    }
  } catch (err) {
    console.error("Stripe webhook handling failed", { eventId: event.id, err });
    return NextResponse.json({ error: "Webhook handler failed" }, { status: 500 }); // ให้ Stripe retry
  }

  return NextResponse.json({ received: true });
}
```

### 5. Checkout เชื่อราคาและจำนวนจาก client

- **Location:** `app/api/checkout/route.ts:13-37`
- **Severity:** High
- **Category:** Security
- **Confidence:** High

**Root cause:** `subtotal` คำนวณจาก `item.price` ที่ client ส่งมา (บรรทัด 24) และบันทึกเป็น `unitPrice` (บรรทัด 37) ทั้งที่โหลด `product` จาก DB มาแล้ว body ถูก cast ด้วย `as { items: CartItem[] }` โดยไม่ validate ทำให้ `quantity` ติดลบหรือเป็นทศนิยมได้

**Impact / trigger:** ผู้ใช้ที่ login แล้วส่ง `{"items":[{"productId":"...","quantity":1,"price":0.01}]}` จะได้ order ราคา 0.01 บาท หรือใส่ `quantity: -5` ให้ subtotal ติดลบ (ผ่านเช็ค `stock < quantity` ด้วย) ถ้า flow ชำระเงินใช้ `order.total` ก็คือจ่ายเท่าที่ตัวเองกำหนด

**Fix:** validate ด้วย zod และใช้ `product.price` จาก DB (รวมกับการแก้ finding 10)

```ts
const checkoutSchema = z.object({
  items: z
    .array(z.object({ productId: z.string().cuid(), quantity: z.number().int().min(1).max(100) }))
    .min(1),
});

const parsed = checkoutSchema.safeParse(await req.json());
if (!parsed.success) return NextResponse.json({ error: "Invalid cart" }, { status: 400 });
const { items } = parsed.data;

const products = await db.product.findMany({ where: { id: { in: items.map((i) => i.productId) } } });
const byId = new Map(products.map((p) => [p.id, p]));

let subtotal = 0;
for (const item of items) {
  const product = byId.get(item.productId);
  if (!product || product.stock < item.quantity) {
    return NextResponse.json({ error: `Out of stock: ${item.productId}` }, { status: 409 });
  }
  subtotal += product.price * item.quantity; // ราคาจาก DB เท่านั้น
}
// ... ตอนสร้าง order items ใช้ unitPrice: byId.get(i.productId)!.price
```

### 6. IDOR: ลบ order ของผู้ใช้อื่นได้

- **Location:** `app/api/orders/[id]/route.ts:27-28`
- **Severity:** High
- **Category:** Security
- **Confidence:** High

**Root cause:** `DELETE` เช็คแค่ว่า login แล้ว แต่ลบด้วย `where: { id }` โดยไม่ผูกกับ `userId` (ต่างจาก `GET` ด้านบนที่ทำถูกแล้ว) และไม่เช็คสถานะ order

**Impact / trigger:** ผู้ใช้คนไหนก็ได้ที่ได้ order id ของคนอื่น (เช่นจาก finding 1 หรือเห็นใน URL) เรียก `DELETE /api/orders/<id>` ลบ order ของคนอื่นได้ รวมถึง order ที่ `PAID` แล้ว นอกจากนี้ถ้า id ไม่มีอยู่ `db.order.delete` จะ throw ทำให้ได้ 500 แทน 404

**Fix:**

```ts
const { id } = await params;
const { count } = await db.order.deleteMany({
  where: { id, userId: user.id, status: "PENDING" }, // ลบได้เฉพาะของตัวเองที่ยังไม่จ่าย
});
if (count === 0) return NextResponse.json({ error: "Not found" }, { status: 404 });
return NextResponse.json({ ok: true });
```

### 7. Stored XSS ผ่าน `product.description`

- **Location:** `app/products/[slug]/page.tsx:18`
- **Severity:** High
- **Category:** Security
- **Confidence:** Medium (ขึ้นกับว่าใครเขียน `description` ได้บ้าง ซึ่งดูไม่ได้จากโค้ดที่ส่งมา)

**Root cause:** `description` จาก DB ถูก render เป็น HTML ดิบด้วย `dangerouslySetInnerHTML` โดยไม่ sanitize (ส่วน `review.body` / `review.user.name` render เป็น JSX text ซึ่ง React escape ให้แล้ว ไม่เป็นปัญหา)

**Impact / trigger:** ถ้า description ถูกนำเข้าจากแหล่งภายนอก, แก้ไขโดย staff หลายคน, หรือถูกแก้ผ่านช่องโหว่อื่น (เช่น finding 2 ที่ยึดสิทธิ์ admin ได้) การใส่ `<img src=x onerror="...">` จะรัน script ในเบราว์เซอร์ของลูกค้าทุกคนที่เปิดหน้าสินค้า

**Fix:** ถ้าไม่จำเป็นต้องเป็น HTML ให้ render เป็นข้อความ ถ้าจำเป็นให้ sanitize ฝั่ง server ด้วย allowlist (เช่น `isomorphic-dompurify`) ตอนบันทึกหรือก่อน render

```tsx
// ทางที่ง่ายที่สุด
<section style={{ whiteSpace: "pre-line" }}>{product.description}</section>

// หรือถ้าต้องการ HTML จริง
import DOMPurify from "isomorphic-dompurify";
<section dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(product.description, { USE_PROFILES: { html: true } }) }} />
```

### 8. `GET /api/users` ส่ง User entity ทั้งก้อนกลับไป

- **Location:** `app/api/users/route.ts:11-13`
- **Severity:** High
- **Category:** Security
- **Confidence:** Medium (ไม่เห็น Prisma schema แต่ app ที่ใช้ next-auth + credentials มักมี `passwordHash` / token field)

**Root cause:** `findMany` ไม่มี `select` และ `{ ...u }` spread ทุก field ลง response รวมถึง field ลับ เช่น `passwordHash`, reset token ถึงจะจำกัดเฉพาะ ADMIN แต่ข้อมูลนี้ไม่ควรออกจาก server เลย

**Impact / trigger:** admin (หรือคนที่ได้ ADMIN มาจาก finding 2) เรียก endpoint นี้แล้วได้ password hash ของผู้ใช้ 100 คนล่าสุด ไปทำ offline cracking ได้ และข้อมูลจะอยู่ใน browser cache / log ด้วย

**Fix:**

```ts
const users = await db.user.findMany({
  select: { id: true, name: true, email: true, role: true, createdAt: true },
  orderBy: { createdAt: "desc" },
  take: 100,
});
const result = users.map((u) => ({ ...u, displayName: u.name || u.email }));
```

### 9. `useEffect` ไม่มี dependency array ทำให้ fetch วนไม่สิ้นสุด

- **Location:** `app/dashboard/page.tsx:12-17`
- **Severity:** High
- **Category:** Correctness
- **Confidence:** High

**Root cause:** effect ไม่มี dependency array จึงรันหลังทุก render และทุกครั้งที่ fetch เสร็จจะ `setOrders(data)` ด้วย array ใหม่ ทำให้ re-render แล้วยิง fetch อีกรอบวนไปเรื่อย ๆ นอกจากนี้ไม่เช็ค `res.ok` ถ้าได้ 401 จะ `setOrders({ error: "Unauthorized" })` แล้ว `orders.map` crash

**Impact / trigger:** ผู้ใช้ทุกคนที่เปิด `/dashboard` จะยิง `/api/orders` หลายสิบครั้งต่อวินาทีจนกว่าจะปิดแท็บ กดดัน DB และหน้า crash เมื่อ session หมดอายุ

**Fix:** ใส่ `[]` และเช็ค `res.ok` (ระยะยาวควรเปลี่ยนเป็น Server Component ที่ดึงข้อมูลบน server ซึ่งจะแก้ finding 3 ไปด้วยเพราะไม่ต้อง import config ฝั่ง client)

```tsx
useEffect(() => {
  let cancelled = false;
  fetch("/api/orders")
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json() as Promise<Order[]>;
    })
    .then((data) => { if (!cancelled) setOrders(data); })
    .catch(() => { if (!cancelled) setError("Failed to load orders"); });
  return () => { cancelled = true; };
}, []);
```

### 10. Checkout: N+1 query และไม่มี transaction / ไม่ตัด stock

- **Location:** `app/api/checkout/route.ts:19-40`
- **Severity:** Medium
- **Category:** Performance / Correctness
- **Confidence:** Medium (อาจมีการตัด stock ที่อื่น เช่นใน webhook แต่ไม่พบในโค้ดที่ส่งมา)

**Root cause:** เรียก `findUnique` ทีละสินค้าในลูป (N+1) และเช็ค stock แยกจากการสร้าง order โดยไม่มี transaction ทั้งไม่มีการลด `stock` เลย

**Impact / trigger:** ตะกร้า 30 รายการ = 30 query ต่อ request และเมื่อมีสองคน checkout สินค้าชิ้นสุดท้ายพร้อมกัน ทั้งคู่ผ่านเช็ค stock ได้ (oversell)

**Fix:** ใช้ `findMany({ where: { id: { in } } })` ตามตัวอย่างใน finding 5 และทำการลด stock กับสร้าง order ใน `db.$transaction` โดยใช้ conditional update เช่น `db.product.updateMany({ where: { id, stock: { gte: qty } }, data: { stock: { decrement: qty } } })` แล้ว rollback ถ้า `count === 0`

### 11. Business logic ด้านราคาอยู่ใน route handler

- **Location:** `app/api/checkout/route.ts:18-29`
- **Severity:** Medium
- **Category:** Architecture
- **Confidence:** High

**Root cause:** กฎ "ส่งฟรีเมื่อ ≥ 1000", "ค่าส่ง 50", "VAT 7%" เป็น magic number อยู่ใน handler ทำให้ unit test ไม่ได้ และเมื่อหน้า cart / email / admin ต้องแสดงยอดเดียวกันจะต้อง copy สูตรไปซ้ำแล้วไม่ตรงกันในที่สุด

**Fix:** ย้ายไป `lib/services/pricing.ts` (เช่น `calculateOrderTotal(lines)` ที่คืน `{ subtotal, shipping, vat, total }`) พร้อมค่าคงที่ที่มีชื่อ แล้วให้ handler แค่ validate, authorize และเรียก service นอกจากนี้ VAT ปัดเศษแต่ `subtotal`/`total` ไม่ปัด ควรคำนวณเป็นสตางค์ (integer) ทั้งหมดเพื่อเลี่ยง floating-point error

### 12. `revalidatePath` ไม่ตรงกับ route จริง

- **Location:** `app/actions/review.ts:26`
- **Severity:** Low
- **Category:** Correctness
- **Confidence:** Medium

**Root cause / fix:** หน้าสินค้าอยู่ที่ `/products/[slug]` แต่ revalidate `/products/${productId}` ซึ่งไม่ใช่ path ที่มีอยู่ ถ้าหน้าถูก cache ไว้ review ใหม่จะไม่ขึ้น ให้ดึง `slug` ของสินค้า (`db.product.findUnique({ where: { id }, select: { slug: true } })`) แล้ว revalidate path นั้น หรือใช้ `revalidatePath("/products/[slug]", "page")` การดึงสินค้าก่อนยังช่วยคืน error ที่อ่านรู้เรื่องเมื่อ `productId` ไม่มีอยู่ (ตอนนี้ foreign key error จะ throw เป็น 500)

### 13. รวม Low: type safety และประสิทธิภาพเล็กน้อย

- **Location:** `lib/auth.ts:8`, `app/api/users/route.ts:12`, `app/api/orders/route.ts:13-15`, `app/api/reviews/route.ts:6,23-24`
- **Severity:** Low
- **Category:** Type safety / Performance
- **Confidence:** High

- `lib/auth.ts:8` — `session.user as SessionUser` cast โดยไม่เช็คว่ามี `id`/`role` จริง ถ้า callback ของ next-auth ไม่ได้ใส่ `role` ลง session เช็ค `role !== "ADMIN"` ยังปลอดภัย แต่ `user.id` อาจเป็น `undefined` แบบเงียบ ๆ ควรขยาย type ผ่าน module augmentation ของ next-auth หรือเช็ค field ก่อนคืนค่า
- `app/api/users/route.ts:12` — `(u: any)` ไม่จำเป็น Prisma infer type ให้แล้ว (หายไปเมื่อแก้ finding 8)
- `app/api/orders/route.ts` — list ไม่มี `LIMIT` / pagination (แก้ไปพร้อม finding 1 ด้วย `take`)
- `app/api/reviews/route.ts:23-24` — endpoint รายการ review เรียก Stripe API ทุก request เพื่อเอาราคา ซึ่งช้าและกิน rate limit ควรเก็บราคาไว้ใน DB (มี `product.price` อยู่แล้ว) หรือ cache และใช้ Stripe client จาก `lib/stripe.ts` ร่วมกัน

## What's done well

- `app/actions/review.ts` เป็นตัวอย่างที่ดีของ Server Action: เช็ค session ก่อน, validate ด้วย zod schema ที่ระบุ field ชัดเจน, และเอา `userId` จาก session ไม่ใช่จาก form ควรใช้เป็น pattern สำหรับ `updateProfile`
- `GET /api/orders/[id]` ผูก `userId: user.id` ไว้ใน `where` และคืน 404 เมื่อไม่พบ ป้องกัน IDOR ได้ถูกต้อง
- `app/api/reviews/route.ts` ใช้ `$queryRaw` แบบ tagged template (parameterized) พร้อม validate `productId` และ `LIMIT 50`
- `app/api/users/route.ts` เช็ค role ADMIN และมี `take: 100`
- `lib/db.ts` ใช้ Prisma singleton บน `globalThis` ถูกต้อง และ `tsconfig.json` เปิด `strict: true`

## Notes

- ไม่มี `middleware.ts` ในโปรเจค จึงถือว่าทุก route/action ต้องเช็ค auth เอง
- ไม่ได้เห็นไฟล์ `@/auth` (next-auth config) และ `prisma/schema.prisma` finding 8 และ 13 (ข้อ `SessionUser`) ขึ้นกับสองไฟล์นี้
- ไม่ได้รัน build/test ทุก finding มาจากการอ่านโค้ดและ trace data flow
- ลำดับการแก้ที่แนะนำ: rotate Stripe secret key (3) → 1, 2, 4 → 5, 6 → 7, 8, 9 → ที่เหลือ
