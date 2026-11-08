export const config = {
  appName: "Shop Admin",
  stripePublishableKey: process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY ?? "",
  stripeSecretKey: process.env.NEXT_PUBLIC_STRIPE_SECRET_KEY ?? "",
  currency: "thb",
};
