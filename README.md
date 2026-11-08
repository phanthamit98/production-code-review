# production-code-review

AI Skill สำหรับ **รีวิวโค้ดแบบรู้จัก stack** ของ Next.js (App Router, Route Handlers, Server Actions, React) และ ASP.NET Core / .NET (Web API, EF Core)
หา security hole, authorization ที่ขาด, error ที่ถูกกลืน, การวาง layer ผิด, type safety และ performance trap แล้ว **ตรวจยืนยันทุกข้อกับพฤติกรรมจริงของ framework** ก่อนรายงาน เพื่อลด false positive
ผลลัพธ์เป็นรายงานรูปแบบตายตัว: `ไฟล์:บรรทัด`, ระดับความรุนแรง, root cause, วิธีแก้เป็นโค้ด และ verdict ว่า merge ได้หรือไม่

## ปัญหาที่ Skill นี้แก้

การให้ AI "ช่วยรีวิวโค้ดหน่อย" แบบไม่มีกรอบมักเจอ 3 ปัญหา

1. **พลาดบั๊กอันตราย** เช่น IDOR หรือ Server Action ที่ใครก็เรียกได้ เพราะอ่านไฟล์เรียงไปเรื่อยๆ ไม่ได้ไล่ตามเส้นทางของ input
2. **แจ้งเตือนผิด** เช่น บอกว่า `{value}` ใน JSX เป็น XSS หรือ `FromSqlInterpolated` เป็น SQL injection ทั้งที่ framework จัดการให้แล้ว
3. **รูปแบบไม่สม่ำเสมอ** บางครั้งมีเลขบรรทัด บางครั้งไม่มี ไม่มีระดับความรุนแรง ไม่บอกว่าควร merge ไหม

## โครงสร้าง

```
production-code-review-project/
├── production-code-review/            ← ตัว Skill (ติดตั้งโฟลเดอร์นี้)
│   ├── SKILL.md                       ← frontmatter + Input / Workflow / Output
│   ├── references/
│   │   ├── core-checklist.md          ← checklist กลางทุก stack (6 หมวด)
│   │   ├── nextjs.md                  ← เฉพาะ Next.js + รายการ "ไม่ใช่บั๊ก"
│   │   ├── dotnet.md                  ← เฉพาะ ASP.NET Core + รายการ "ไม่ใช่บั๊ก"
│   │   └── severity-and-verification.md ← เกณฑ์ระดับความรุนแรง + ขั้นตอนตัด false positive
│   ├── assets/report-template.md      ← รูปแบบรายงาน
│   ├── scripts/detect_stack.py        ← ตรวจ stack, entry point, middleware/pipeline (Python stdlib)
│   └── evals/                         ← test case (รูปแบบเดียวกับ `claude plugin eval`)
│       ├── review-nextjs-shop/        ← โปรเจค Next.js ฝังปัญหา 13 จุด + decoy 4 จุด
│       └── review-dotnet-inventory/   ← โปรเจค .NET ฝังปัญหา 12 จุด + decoy 4 จุด
├── benchmark/
│   ├── answer-key.md                  ← เฉลย (อยู่นอก Skill เพื่อไม่ให้ AI ที่ถูกทดสอบเห็น)
│   ├── results.md                     ← ผลเปรียบเทียบ AI ปกติ vs AI + Skill
│   └── reports/                       ← รายงานจริงที่แต่ละฝั่งเขียนออกมา
└── README.md
```

## Input / Workflow / Output

**Input** (อย่างใดอย่างหนึ่ง)
- path ของไฟล์หรือโฟลเดอร์
- diff / PR / branch (`git diff main...HEAD`)
- โค้ดที่วางในแชท

**Workflow**

1. **Map project** — รัน `detect_stack.py` หา stack, entry point ทั้งหมด (Route Handler, Server Action, Controller action, Minimal API) และสิ่งที่ป้องกันอยู่แล้ว (middleware matcher, `[Authorize]` ระดับ class, ลำดับ pipeline) แล้วโหลดเฉพาะ reference ที่ตรง stack
2. **Trace untrusted input** — ไล่จาก entry point: validate ไหม → authenticate ไหม → authorize *record นี้* ไหม → ไปจบที่ SQL / HTML / response
3. **Review แยกรอบ** — Security → Correctness → Architecture → Type safety → Performance → Maintainability
4. **Verify ทุก finding** — อ่านซ้ำ, หาว่ามีอะไรป้องกันอยู่แล้วหรือไม่, เช็คพฤติกรรม framework, ต้องอธิบายวิธี trigger ได้
5. **จัดระดับ** ตามเกณฑ์ (impact × likelihood ในโค้ดนี้)
6. **เขียนรายงาน** ตาม template

**Output** — `code-review-report.md`
- ตารางสรุปจำนวนตามระดับ + ตาราง finding
- แต่ละ finding: Location (`file:line`), Severity, Category, Confidence, Root cause, Impact/trigger, Fix (โค้ดสำหรับ Critical/High)
- What's done well, Notes (สิ่งที่ไม่ได้ตรวจ / สมมติฐาน)
- **Verdict:** Block / Approve with changes / Approve

## การติดตั้ง

**Claude Code**
```bash
# ระดับผู้ใช้ (ใช้ได้ทุกโปรเจค)
cp -r production-code-review ~/.claude/skills/
# หรือระดับโปรเจค (commit ให้ทีมใช้ร่วมกัน)
cp -r production-code-review <your-repo>/.claude/skills/
```

**Claude.ai / Claude Desktop** — zip โฟลเดอร์ `production-code-review` แล้วอัปโหลดที่ Settings → Capabilities → Skills (หรือใช้ไฟล์ `.skill` ที่แนบมา)

ต้องมี Python 3.8+ สำหรับ `detect_stack.py` (ไม่ต้องติดตั้ง package เพิ่ม)

## วิธีใช้งาน

Skill จะทำงานอัตโนมัติเมื่อขอให้รีวิว/ตรวจโค้ด ไม่จำเป็นต้องเรียกชื่อ

```text
รีวิวโปรเจคนี้ก่อน merge หน่อย
ตรวจ PR นี้เทียบกับ main ให้หน่อย โฟกัส security
Review src/app/api for anything unsafe before we deploy
ตรวจ InventoryApi/Controllers ให้หน่อย เขียนผลไว้ที่ docs/review.md
```

เรียกตรงๆ ใน Claude Code: `/production-code-review src/app`

ใช้ detector แยกได้:
```bash
python production-code-review/scripts/detect_stack.py <project-root>
```

### ปรับให้เข้ากับทีม

- เพิ่มกฎของทีมใน `references/core-checklist.md` หรือไฟล์ stack ที่เกี่ยวข้อง
- เพิ่มสิ่งที่ทีมใช้แล้ว "ไม่ใช่บั๊ก" ในหัวข้อ *Not bugs* เพื่อลด false positive
- ต้องการ stack ใหม่ (เช่น NestJS, Go): เพิ่ม `references/<stack>.md` และเพิ่มการตรวจใน `detect_stack.py`

## การทดสอบและผลเปรียบเทียบ

ดูรายละเอียดเต็มที่ [`benchmark/results.md`](benchmark/results.md)

ทดสอบกับโปรเจค Next.js และ .NET ที่ฝังปัญหาไว้ 25 จุด + โค้ดปลอดภัยที่ดูเหมือนผิด 8 จุด ให้คะแนนแบบ blind

| | AI + Skill | AI ปกติ |
|---|---|---|
| Pass rate รวม (41 ข้อ) | **97.5%** | 85.4% |
| จับปัญหาที่ฝังไว้ | **25/25** | 23/25 |
| ปัญหา architecture | **2/2** | 0/2 |
| แจ้งเตือนผิด | 0 | 0 |
| Critical/High มีโค้ดแก้ครบ | **2/2 case** | 0/2 case |
| จำนวน finding เฉลี่ย | **14** (กระชับกว่า ~40%) | 23.5 |
| ต้นทุน | +12% tokens, +26% เวลา | — |

สรุป: การจับช่องโหว่ security โมเดลปกติทำได้ดีอยู่แล้ว Skill ช่วยเรื่อง **ปัญหา architecture, รายงานที่มีเลขบรรทัดและโค้ดแก้ครบ และความกระชับ**

### รันซ้ำเอง

ด้วย Claude Code v2.1.269 ขึ้นไป (รันจริง มีค่าใช้จ่าย):
```bash
cd production-code-review
claude plugin eval . --allow-tools Write,Edit,Bash --scaffold
```
คำสั่งนี้จะรันทุก case ทั้งแบบมีและไม่มี Skill แล้วให้คะแนนตาม `evals/*/graders/`

## ข้อจำกัด

- Static review เท่านั้น ไม่ได้ compile หรือรันโค้ด
- ทดสอบกับโปรเจคขนาดเล็ก 2 ชุด รันชุดละ 1 รอบ ผลจริงกับโปรเจคใหญ่อาจต่างออกไป
- ไม่แทน SAST/dependency scanner (เช่น `npm audit`, `dotnet list package --vulnerable`) ควรใช้ร่วมกัน
