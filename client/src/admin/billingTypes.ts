export type BillingTariff = {
  enabled: boolean;
  unit_credits: string | null;
  unit_cost_fen: string | null;
  unit_rounding: "ceil" | "exact";
  version: number;
};

export type BillingService = {
  service: string;
  name: string;
  unit: "second" | "image" | "call";
  provider: string;
  module: string;
  customer_charge_allowed: boolean;
  configured: boolean;
  tariff: BillingTariff;
};

export const billingUnit = { second: "秒", image: "张", call: "次" };
