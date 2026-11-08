import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { getSessionUser } from "@/lib/auth";

export async function GET(req: NextRequest) {
  const user = await getSessionUser();
  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const status = req.nextUrl.searchParams.get("status") ?? "PENDING";

  const orders = await db.$queryRawUnsafe(
    `SELECT id, total, status, "createdAt" FROM "Order" WHERE "userId" = '${user.id}' AND status = '${status}' ORDER BY "createdAt" DESC`
  );

  return NextResponse.json(orders);
}
