import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import Stripe from "stripe";
import { db } from "@/lib/db";

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);

const querySchema = z.object({ productId: z.string().cuid() });

export async function GET(req: NextRequest) {
  const parsed = querySchema.safeParse({ productId: req.nextUrl.searchParams.get("productId") });
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid productId" }, { status: 400 });
  }

  const reviews = await db.$queryRaw`
    SELECT r.id, r.rating, r.body, u.name AS "authorName"
    FROM "Review" r JOIN "User" u ON u.id = r."userId"
    WHERE r."productId" = ${parsed.data.productId}
    ORDER BY r."createdAt" DESC
    LIMIT 50`;

  const product = await db.product.findUnique({ where: { id: parsed.data.productId } });
  const price = product?.stripePriceId ? await stripe.prices.retrieve(product.stripePriceId) : null;

  return NextResponse.json({ reviews, unitAmount: price?.unit_amount ?? null });
}
