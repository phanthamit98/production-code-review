import { notFound } from "next/navigation";
import { db } from "@/lib/db";

type Props = { params: Promise<{ slug: string }> };

export default async function ProductPage({ params }: Props) {
  const { slug } = await params;
  const product = await db.product.findUnique({
    where: { slug },
    include: { reviews: { include: { user: { select: { name: true } } }, take: 20 } },
  });
  if (!product) notFound();

  return (
    <main>
      <h1>{product.name}</h1>
      <p>{product.price.toFixed(2)} THB</p>
      <section dangerouslySetInnerHTML={{ __html: product.description }} />
      <h2>Reviews</h2>
      <ul>
        {product.reviews.map((review) => (
          <li key={review.id}>
            <strong>{review.user.name}</strong> ({review.rating}/5)
            <p>{review.body}</p>
          </li>
        ))}
      </ul>
    </main>
  );
}
