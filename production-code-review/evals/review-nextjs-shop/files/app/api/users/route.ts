import { NextResponse } from "next/server";
import { db } from "@/lib/db";
import { getSessionUser } from "@/lib/auth";

export async function GET() {
  const user = await getSessionUser();
  if (!user || user.role !== "ADMIN") {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  const users = await db.user.findMany({ orderBy: { createdAt: "desc" }, take: 100 });
  const result = users.map((u: any) => ({ ...u, displayName: u.name || u.email }));
  return NextResponse.json(result);
}
