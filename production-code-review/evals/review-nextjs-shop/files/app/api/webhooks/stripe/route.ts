import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";

export async function POST(req: NextRequest) {
  try {
    const event = await req.json();

    if (event.type === "checkout.session.completed") {
      const orderId = event.data.object.metadata.orderId;
      await db.order.update({ where: { id: orderId }, data: { status: "PAID" } });
    }
  } catch (err) {}

  return NextResponse.json({ received: true });
}
