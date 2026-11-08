import { auth } from "@/auth";

export type SessionUser = { id: string; email: string; role: "USER" | "ADMIN" };

export async function getSessionUser(): Promise<SessionUser | null> {
  const session = await auth();
  if (!session?.user) return null;
  return session.user as SessionUser;
}
