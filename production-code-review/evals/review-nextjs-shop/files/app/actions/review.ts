"use server";

import { z } from "zod";
import { revalidatePath } from "next/cache";
import { db } from "@/lib/db";
import { getSessionUser } from "@/lib/auth";

const reviewSchema = z.object({
  productId: z.string().cuid(),
  rating: z.coerce.number().int().min(1).max(5),
  body: z.string().trim().min(1).max(2000),
});

export async function createReview(formData: FormData) {
  const user = await getSessionUser();
  if (!user) {
    return { error: "Please sign in to leave a review." };
  }

  const parsed = reviewSchema.safeParse(Object.fromEntries(formData));
  if (!parsed.success) {
    return { error: "Invalid review." };
  }

  await db.review.create({ data: { ...parsed.data, userId: user.id } });
  revalidatePath(`/products/${parsed.data.productId}`);
  return { ok: true };
}
