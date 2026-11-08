# Code Review Report: shop-admin (Next.js 15)

**วันที่รีวิว:** 2026-11-09
**ขอบเขต:** ไฟล์ทั้งหมดในโปรเจค (`app/`, `lib/`, `package.json`, `tsconfig.json`) รวม 15 ไฟล์ ประมาณ 300 บรรทัด
**ข้อสรุป:** **ยังไม่ควร merge เข้า main** ตอนนี้มีช่องโหว่ระดับ Critical 7 ข้อ ข้อที่หนักที่สุดคือ แก้ราคาสินค้าเองได้, ปลอมสถานะว่าจ่ายเงินแล้วได้, ยกระดับสิทธิ์ตัวเองเป็น ADMIN ได้, ทำ SQL injection ได้ และ Stripe secret key รั่วไปถึงฝั่ง browser

---

## สรุปตามระดับความรุนแรง

| ระดับ | จำนวน | ความหมาย |
|---|---|---|
| Critical | 7 | ต้องแก้ก่อน merge โดนโจมตีได้จริง เสียเงินหรือข้อมูลรั่วทันที |
| High | 5 | ต้องแก้ก่อน merge เป็นบั๊กหรือช่องโหว่ที่กระทบผู้ใช้จริง |
| Medium | 7 | ควรแก้ใน PR นี้หรือเปิด ticket ติดตาม |
| Low / Nit | 6 | ปรับปรุงคุณภาพโค้ด |
| **รวม** | **25** | |

---

## Critical

### C1. SQL Injection ใน `GET /api/orders`
**ไฟล์:** `app/api/orders/route.ts:11-15`

```ts
const status = req.nextUrl.searchParams.get("status") ?? "PENDING";
const orders = await db.$queryRawUnsafe(
  `SELECT ... WHERE "userId" = '${user.id}' AND status = '${status}' ...`
);
```
ค่า `status` มาจาก query string โดยตรงแล้วต่อลงใน SQL ผ่าน `$queryRawUnsafe` เช่นส่ง `?status=' OR '1'='1` ก็จะเห็นออเดอร์ของทุกคน และใช้ `UNION SELECT` ดึงข้อมูลตารางอื่นได้ (เช่น `User`)

**วิธีแก้:** ใช้ Prisma query builder และตรวจค่า status ด้วย enum
```ts
const status = z.enum(["PENDING", "PAID", "SHIPPED", "CANCELLED"]).catch("PENDING")
  .parse(req.nextUrl.searchParams.get("status"));
const orders = await db.order.findMany({
  where: { userId: user.id, status },
  select: { id: true, total: true, status: true, createdAt: true },
  orderBy: { createdAt: "desc" },
});
```
ถ้าจำเป็นต้องใช้ raw SQL จริงๆ ให้ใช้ `` db.$queryRaw`...${value}` `` (tagged template ซึ่ง parameterize ให้) ไม่ควรใช้ `$queryRawUnsafe` กับ input จากผู้ใช้เลย

### C2. Checkout เชื่อราคาที่ client ส่งมา (Price tampering)
**ไฟล์:** `app/api/checkout/route.ts:5, 24, 37`

`subtotal += item.price * item.quantity;` และ `unitPrice: i.price` ใช้ `price` จาก request body ผู้ใช้จึงส่ง `price: 0.01` (หรือติดลบ) แล้วสั่งสินค้าราคาเท่าไหร่ก็ได้ ระบบไม่ได้ใช้ `product.price` จาก DB ที่ query มาแล้วเลย

นอกจากนี้ยังไม่ validate `quantity` ส่ง `quantity: -5` หรือ `quantity: 1.5` ได้ ถ้า quantity ติดลบ ยอด total ก็ติดลบ และผ่านเงื่อนไข `product.stock < item.quantity` ได้เสมอ

**วิธีแก้:**
- ใช้ zod ตรวจ body: `items: z.array(z.object({ productId: z.string().cuid(), quantity: z.number().int().positive().max(100) })).min(1)` และตัด field `price` ออกจาก input ไปเลย
- ใช้ `product.price` จาก DB เท่านั้น

### C3. Stripe webhook ไม่ตรวจลายเซ็น ใครก็ mark ออเดอร์เป็น PAID ได้
**ไฟล์:** `app/api/webhooks/stripe/route.ts`

endpoint รับ JSON ไหนก็ได้แล้วอัปเดต `status: "PAID"` ทันที ผู้โจมตีแค่ POST `{"type":"checkout.session.completed","data":{"object":{"metadata":{"orderId":"<id>"}}}}` ก็ได้ของฟรี ประกอบกับ C2 ก็ทำให้ไม่ต้องจ่ายเงินเลยแม้แต่บาทเดียว

ปัญหาเพิ่มเติม:
- `catch (err) {}` กลืน error ทั้งหมดแล้วตอบ 200 Stripe จึงไม่ retry และไม่มี log ให้ debug
- ไม่ได้เทียบ `amount_total` / `currency` ของ session กับ `order.total`
- ไม่มี idempotency (Stripe ส่ง event ซ้ำได้)

**วิธีแก้:**
```ts
const body = await req.text();
const sig = req.headers.get("stripe-signature")!;
let event: Stripe.Event;
try {
  event = stripe.webhooks.constructEvent(body, sig, process.env.STRIPE_WEBHOOK_SECRET!);
} catch {
  return NextResponse.json({ error: "Invalid signature" }, { status: 400 });
}
// ตรวจ amount_total กับ order.total แล้วค่อยอัปเดต (where: { id, status: "PENDING" })
// error อื่นๆ ให้ log และตอบ 500 เพื่อให้ Stripe retry
```

### C4. Server Action `updateProfile` ไม่มี auth และรับทุก field (IDOR + Mass assignment → privilege escalation)
**ไฟล์:** `app/actions/profile.ts`

- Server Action เป็น public HTTP endpoint ใครจะเรียกก็ได้ แต่ฟังก์ชันนี้รับ `userId` เป็น argument จาก client โดยไม่เช็ค session เลย จึงแก้ profile ของใครก็ได้
- `data = Object.fromEntries(formData)` แล้วส่งให้ `db.user.update` ตรงๆ ผู้ใช้จึงส่ง `role=ADMIN`, `email=...` หรือ `passwordHash=...` มาได้ ผลคือยึดสิทธิ์ admin หรือยึดบัญชีคนอื่นได้

**วิธีแก้:** ดึง user จาก `getSessionUser()` ไม่รับ userId จาก client และใช้ zod schema แบบ whitelist field (เช่น `name`, `phone`) เหมือนที่ `createReview` ทำ

### C5. Stripe Secret Key รั่วไปยัง browser
**ไฟล์:** `lib/config.ts:4`, `app/dashboard/page.tsx:4`

`process.env.NEXT_PUBLIC_STRIPE_SECRET_KEY` ใช้ prefix `NEXT_PUBLIC_` Next.js จะ inline ค่านี้ลง JS bundle ฝั่ง client และ `config` ก็ถูก import ใน `"use client"` component (`dashboard/page.tsx`) ด้วย secret key จึงอยู่ในไฟล์ JS ที่ใครก็โหลดได้ ใช้ทำ refund, สร้าง charge หรืออ่านข้อมูลลูกค้าใน Stripe ได้

**วิธีแก้:**
- **Rotate Stripe secret key ทันที** ถ้าเคย deploy หรือ build preview ไปแล้ว
- ลบ `stripeSecretKey` ออกจาก `config.ts` ใช้ `process.env.STRIPE_SECRET_KEY` เฉพาะในโค้ดฝั่ง server (แยกเป็น `lib/stripe.ts` และใส่ `import "server-only"`)

### C6. `DELETE /api/orders/[id]` ลบออเดอร์ของคนอื่นได้ (IDOR)
**ไฟล์:** `app/api/orders/[id]/route.ts:27-28`

GET เช็ค `userId` แล้ว แต่ DELETE ใช้ `where: { id }` อย่างเดียว user ที่ login อยู่จึงลบออเดอร์ของใครก็ได้ ยังลบออเดอร์ที่ PAID แล้วได้ด้วย ซึ่งทำให้ข้อมูลบัญชีหาย ถ้า id ไม่มีอยู่จริง Prisma จะ throw P2025 แล้วกลายเป็น 500

**วิธีแก้:** `db.order.deleteMany({ where: { id, userId: user.id, status: "PENDING" } })` แล้วเช็ค `count === 0` เพื่อตอบ 404 หรือดีกว่านั้นคือเปลี่ยนเป็น soft cancel (`status: "CANCELLED"`) แทนการลบจริง

### C7. Dependency มีช่องโหว่ที่รู้กันแล้ว (Next.js 15.1.0 / React 19.0.0)
**ไฟล์:** `package.json`

- `next@15.1.0` + `react@19.0.0` อยู่ในช่วงเวอร์ชันที่โดนช่องโหว่ RCE ของ React Server Components (CVE-2025-55182 / Next.js CVE-2025-66478, ธ.ค. 2025) โปรเจคนี้ใช้ Server Actions อยู่แล้วจึงได้รับผลกระทบโดยตรง
- `next@15.1.0` ยังโดน CVE-2025-29927 (middleware authorization bypass) ด้วย ตอนนี้ยังไม่มี middleware แต่ถ้าเพิ่มทีหลังก็จะโดนทันที

**วิธีแก้:** อัปเกรด `next`, `react` และ `react-dom` เป็น patch ล่าสุดของ 15.x แล้วรัน `npm audit` ยืนยัน และ commit lockfile (ตอนนี้ไม่มี `package-lock.json`/`pnpm-lock.yaml`)

---

## High

### H1. Stored XSS ผ่าน `dangerouslySetInnerHTML`
**ไฟล์:** `app/products/[slug]/page.tsx:18`

`product.description` ถูก render เป็น HTML ดิบ ถ้าใครก็ตามที่แก้ description ได้ (admin, import จาก supplier หรือผ่าน C4) ใส่ `<img src=x onerror=...>` สคริปต์จะรันในเบราว์เซอร์ของลูกค้าทุกคนที่เปิดหน้านี้

**วิธีแก้:** sanitize ด้วย `isomorphic-dompurify`/`sanitize-html` ก่อน render หรือเก็บ description เป็น Markdown แล้ว render ด้วย library ที่ปิด raw HTML

### H2. `GET /api/users` ส่งข้อมูล user ทั้ง record ออกไป
**ไฟล์:** `app/api/users/route.ts:11-12`

`findMany` ไม่มี `select` และ `{ ...u }` spread ทุก field ทำให้ field อ่อนไหวอย่าง `passwordHash`, token, ข้อมูลส่วนตัว ฯลฯ ออกไปใน response (ถึงจะเป็น admin ก็ไม่ควรเห็น hash) นอกจากนี้ `u: any` ยังทำให้ TypeScript ช่วยจับปัญหานี้ไม่ได้

**วิธีแก้:** ใช้ `select: { id, email, name, role, createdAt }` และลบ `any` ออก ควรตอบ 401 เมื่อไม่ได้ login และตอบ 403 เมื่อ login แล้วแต่ไม่ใช่ admin

### H3. Dashboard fetch วนไม่รู้จบ (`useEffect` ไม่มี dependency array)
**ไฟล์:** `app/dashboard/page.tsx:12-17`

`useEffect` ไม่มี `[]` จึงรันทุกครั้งที่ render → `setOrders` → render ใหม่ → fetch ใหม่ วนไปเรื่อยๆ ยิง `/api/orders` ไม่หยุด กิน DB และ bandwidth หนักมาก

**วิธีแก้:** ใส่ `[]` และใช้ `AbortController` สำหรับ cleanup หรือดีกว่านั้นคือทำหน้านี้เป็น Server Component แล้ว query DB ตรงๆ (ซึ่งจะแก้ C5 ส่วนที่ import config ไปในตัว)

### H4. Dashboard พังเมื่อ API ตอบ error หรือ `total` ไม่ใช่ number
**ไฟล์:** `app/dashboard/page.tsx:14-15, 28`

- ไม่เช็ค `res.ok` พอ session หมดอายุ API ตอบ `{ error: "Unauthorized" }` แล้วโค้ด `setOrders(object)` → `orders.map is not a function` ทำให้ทั้งหน้า crash
- ถ้า `total` เป็น Prisma `Decimal` ค่าที่ผ่าน JSON จะกลายเป็น string แล้ว `o.total.toFixed` ก็ crash เช่นกัน

**วิธีแก้:** เช็ค `res.ok` และ validate shape ของข้อมูลก่อน set state และส่ง total เป็น number/string ที่ format แล้วจากฝั่ง server

### H5. Checkout ไม่ตัด stock, ไม่ใช้ transaction และ race condition
**ไฟล์:** `app/api/checkout/route.ts:19-40`

- เช็ค stock แต่ไม่ decrement จึงขายเกินสต็อกได้
- เช็คกับสร้างออเดอร์ไม่อยู่ใน transaction เดียวกัน คำขอพร้อมกันหลายอันจึงผ่านทั้งหมด
- `productId` ซ้ำใน cart จะถูกเช็ค stock แยกกัน
- ไม่ได้สร้าง Stripe Checkout Session หรือส่ง `metadata.orderId` ให้ webhook เลย flow การจ่ายเงินยังไม่ครบ (หรืออยู่ที่อื่นที่ไม่ได้อยู่ใน PR นี้ ต้องยืนยัน)

**วิธีแก้:** ใช้ `db.$transaction` ร่วมกับ `updateMany({ where: { id, stock: { gte: qty } }, data: { stock: { decrement: qty } } })` แล้วเช็ค `count` และรวม productId ที่ซ้ำกันก่อนเช็ค stock

---

## Medium

### M1. คำนวณเงินด้วย floating point
**ไฟล์:** `app/api/checkout/route.ts:24-29`
`subtotal` เป็น float เลยเกิดข้อผิดพลาดแบบ `0.1 + 0.2` ได้ ส่วน `total` ไม่ได้ปัดเศษ (มีปัดแค่ VAT) ควรเก็บเป็นหน่วยสตางค์ (integer) หรือใช้ `Prisma.Decimal` และต้องยืนยันด้วยว่าราคาสินค้ารวม VAT อยู่แล้วหรือไม่ (ราคาขายปลีกในไทยส่วนใหญ่รวม VAT แล้ว ถ้าบวก 7% ซ้ำ ลูกค้าก็จะโดนเก็บเกิน)

### M2. Magic numbers ในการคำนวณราคา
**ไฟล์:** `app/api/checkout/route.ts:27-28`
`1000`, `50`, `0.07` ควรย้ายไปเป็น constant หรือ config ที่ตั้งชื่อชัดเจน (`FREE_SHIPPING_THRESHOLD`, `SHIPPING_FEE`, `VAT_RATE`) และควรเขียน unit test ให้ฟังก์ชันคำนวณราคาด้วย

### M3. `req.json()` ไม่มี error handling
**ไฟล์:** `app/api/checkout/route.ts:13`
ถ้า body ไม่ใช่ JSON หรือไม่ใช่ object (`null`) จะ throw แล้วกลายเป็น 500 ควรตอบ 400 การใช้ zod `safeParse` (ตาม C2) จะแก้ข้อนี้ไปด้วย

### M4. N+1 query ใน checkout
**ไฟล์:** `app/api/checkout/route.ts:19-20`
query product ทีละชิ้นใน loop ควรใช้ `findMany({ where: { id: { in: ids } } })` ครั้งเดียว

### M5. `revalidatePath` ผิด path หลังสร้างรีวิว
**ไฟล์:** `app/actions/review.ts:26`
หน้า product ใช้ route `/products/[slug]` แต่ revalidate ด้วย `/products/${productId}` (cuid) หน้าเลยไม่อัปเดต ต้อง query `slug` ก่อน หรือใช้ `revalidatePath("/products/[slug]", "page")` และควรเช็คด้วยว่า product มีอยู่จริง ไม่เช่นนั้นจะเจอ foreign key error เป็น 500

### M6. `GET /api/reviews` เรียก Stripe API ทุก request แบบไม่ต้อง login
**ไฟล์:** `app/api/reviews/route.ts:23-24`
endpoint สาธารณะนี้ยิง `stripe.prices.retrieve` ทุกครั้ง ใครยิงรัวๆ ก็ทำให้โดน rate limit ของ Stripe (กระทบการจ่ายเงินจริง) และเพิ่ม latency นอกจากนี้การดึงราคาก็ไม่เกี่ยวกับรีวิว ควรแยก endpoint หรือใช้ราคาจาก DB/cache หรือ `unstable_cache` ส่วน `new Stripe(process.env.STRIPE_SECRET_KEY!)` ที่ระดับ module ควรย้ายไปที่ `lib/stripe.ts` ที่ fail ชัดเจนเมื่อไม่มี env

### M7. `getSessionUser` cast type โดยไม่ตรวจ
**ไฟล์:** `lib/auth.ts:8`
`session.user as SessionUser` ถ้าใน `auth.ts` ไม่ได้เพิ่ม `id`/`role` ผ่าน callback `jwt`/`session` ค่า `user.id` จะเป็น `undefined` โดยไม่มีใครรู้ (query `where: { userId: undefined }` ของ Prisma จะ**ไม่กรอง**แล้วคืนข้อมูลของทุกคน) ควรเช็ค `id` และ `role` จริงๆ แล้ว return `null` ถ้าไม่มี และไฟล์ `@/auth` (config ของ NextAuth) ก็ไม่อยู่ในโปรเจคนี้ ต้องยืนยันว่ามี callback ดังกล่าวจริง

---

## Low / Nit

- **L1.** `GET /api/orders` ไม่ใส่ `status` แล้ว default เป็น `PENDING` ซึ่งดูไม่ใช่สิ่งที่ dashboard ต้องการ (ควรแสดงทุกสถานะ) และยังไม่มี pagination (`app/api/orders/route.ts:11`)
- **L2.** `GET /api/users` ใช้ `take: 100` ตายตัวโดยไม่มี cursor/pagination (`app/api/users/route.ts:11`)
- **L3.** `createReview` ยังไม่กันรีวิวซ้ำ และไม่เช็คว่าซื้อสินค้านั้นจริงหรือเปล่า (ควรมี unique constraint `[userId, productId]`) และ error message ของ zod ก็ generic เกินไปจนผู้ใช้ไม่รู้ว่าผิดตรงไหน (`app/actions/review.ts`)
- **L4.** Dashboard table ไม่มี `<thead>` และไม่ format สกุลเงิน (ควรใช้ `Intl.NumberFormat("th-TH", { style: "currency", currency: "THB" })`) และไม่มี loading state (`app/dashboard/page.tsx`)
- **L5.** `tsconfig.json` ยังไม่มี `plugins: [{ name: "next" }]`, `include`, `noEmit`, `skipLibCheck`, `isolatedModules`, `esModuleInterop` ตาม template มาตรฐานของ Next.js และ `package.json` ไม่มี script `start`, `lint`, `test`, `typecheck`
- **L6.** ยังไม่มีเทสต์เลย อย่างน้อยควรมีเทสต์สำหรับ checkout (คำนวณราคา/stock), webhook (signature) และ authorization ของ orders/profile ส่วน `next-auth@5.0.0-beta.25` ก็เป็นเวอร์ชัน beta ควร pin และติดตาม release

---

## สิ่งที่ทำได้ดี

- `createReview` ใช้ zod validate input, เช็ค session และกำหนด `userId` จาก server เป็นแบบอย่างที่ดีที่ควรใช้กับ action อื่น
- `GET /api/reviews` ใช้ `$queryRaw` แบบ tagged template (parameterized) และ validate `productId` ด้วย zod
- `GET /api/orders/[id]` scope query ด้วย `userId` ถูกต้อง
- `lib/db.ts` ใช้ pattern singleton ของ PrismaClient ถูกต้อง กันไม่ให้ connection รั่วตอน dev hot reload
- ใช้ `params` แบบ `Promise` ถูกต้องตาม Next.js 15
- เปิด `strict: true` ใน TypeScript

---

## ลำดับการแก้ที่แนะนำ (ก่อน merge)

1. **Rotate Stripe secret key** แล้วลบ `NEXT_PUBLIC_STRIPE_SECRET_KEY` (C5)
2. อัปเกรด Next.js/React เป็น patch ที่ปลอดภัย (C7)
3. ตรวจ signature ของ webhook และเทียบยอดเงิน (C3)
4. ใช้ราคาจาก DB และ validate quantity ใน checkout + ใช้ transaction ตัด stock (C2, H5)
5. แก้ `updateProfile` ให้ใช้ session + whitelist field (C4)
6. แก้ SQL injection (C1) และ IDOR ของ DELETE (C6)
7. Sanitize HTML (H1), จำกัด field ใน `/api/users` (H2), แก้ infinite loop และ error handling ของ dashboard (H3, H4)
8. Medium/Low ทยอยแก้ หรือเปิด ticket ติดตาม

หลังแก้แล้ว ควรเพิ่มเทสต์ของ checkout, webhook และ authorization ก่อนรีวิวรอบถัดไป
