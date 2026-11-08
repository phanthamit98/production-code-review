"use client";

import { useEffect, useState } from "react";
import { config } from "@/lib/config";

type Order = { id: string; total: number; status: string };

export default function DashboardPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/orders")
      .then((res) => res.json())
      .then((data: Order[]) => setOrders(data))
      .catch(() => setError("Failed to load orders"));
  });

  return (
    <main>
      <h1>{config.appName} dashboard</h1>
      {error && <p role="alert">{error}</p>}
      <table>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id}>
              <td>{o.id}</td>
              <td>{o.total.toFixed(2)}</td>
              <td>{o.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
