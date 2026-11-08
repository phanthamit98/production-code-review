import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { getSessionUser } from "@/lib/auth";

type CartItem = { productId: string; quantity: number; price: number };

export async function POST(req: NextRequest) {
  const user = await getSessionUser();
  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { items } = (await req.json()) as { items: CartItem[] };
  if (!Array.isArray(items) || items.length === 0) {
    return NextResponse.json({ error: "Cart is empty" }, { status: 400 });
  }

  let subtotal = 0;
  for (const item of items) {
    const product = await db.product.findUnique({ where: { id: item.productId } });
    if (!product || product.stock < item.quantity) {
      return NextResponse.json({ error: `Out of stock: ${item.productId}` }, { status: 409 });
    }
    subtotal += item.price * item.quantity;
  }

  const shipping = subtotal >= 1000 ? 0 : 50;
  const vat = Math.round(subtotal * 0.07 * 100) / 100;
  const total = subtotal + shipping + vat;

  const order = await db.order.create({
    data: {
      userId: user.id,
      total,
      status: "PENDING",
      items: {
        create: items.map((i) => ({ productId: i.productId, quantity: i.quantity, unitPrice: i.price })),
      },
    },
  });

  return NextResponse.json({ orderId: order.id, total }, { status: 201 });
}
