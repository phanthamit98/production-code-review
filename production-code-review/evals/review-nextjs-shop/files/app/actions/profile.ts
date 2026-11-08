"use server";

import { revalidatePath } from "next/cache";
import { db } from "@/lib/db";

export async function updateProfile(userId: string, formData: FormData) {
  const data = Object.fromEntries(formData);

  await db.user.update({
    where: { id: userId },
    data,
  });

  revalidatePath("/profile");
}
