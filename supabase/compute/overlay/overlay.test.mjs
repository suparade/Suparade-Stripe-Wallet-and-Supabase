// node --test supabase/compute/overlay
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { alertView, formatAmount, paidTip } from "./alerts.mjs";
import handler from "./index.mjs";
import { overlayConfig, publicSupabaseUrl, publishableKey, renderPage } from "./page.mjs";

const CAMPAIGN = "850978ce-6a21-48d7-950f-fcddc2869d70";
const paid = { id: "t1", status: "paid", campaign_id: CAMPAIGN, amount_cents: 750, currency: "usd", message: "Thanks!" };

test("formatAmount renders cents as currency", () => {
  assert.equal(formatAmount(750, "usd"), "$7.50");
  assert.equal(formatAmount(500), "$5.00");
});

test("paidTip announces a paid tip once, for the chosen campaign only", () => {
  assert.equal(paidTip({ new: paid }, CAMPAIGN, new Set()), paid);
  assert.equal(paidTip({ new: paid }, "", new Set()), paid);
  assert.equal(paidTip({ new: { ...paid, status: "pending" } }, CAMPAIGN, new Set()), null);
  assert.equal(paidTip({ new: paid }, "another-campaign", new Set()), null);
  assert.equal(paidTip({ new: paid }, CAMPAIGN, new Set(["t1"])), null);
  assert.equal(paidTip({ eventType: "DELETE", new: {} }, CAMPAIGN, new Set()), null);
});

test("alertView names the brand and the creator", () => {
  assert.deepEqual(alertView(paid, "demo-streamer", "Gatorade"), {
    amount: "$7.50",
    headline: "Gatorade tipped demo-streamer",
    message: "Thanks!",
  });
  assert.equal(alertView(paid, "", "").headline, "A sponsor tipped the streamer");
});

test("publishableKey prefers the anon key, then the publishable keys", () => {
  assert.equal(publishableKey({ SUPABASE_ANON_KEY: "anon", SUPABASE_PUBLISHABLE_KEYS: '{"default":"pub"}' }), "anon");
  assert.equal(publishableKey({ SUPABASE_PUBLISHABLE_KEYS: '{"default":"pub"}' }), "pub");
  assert.equal(publishableKey({ SUPABASE_PUBLISHABLE_KEYS: '{"web":"pub2"}' }), "pub2");
  assert.equal(publishableKey({ SUPABASE_PUBLISHABLE_KEYS: "sb_publishable_raw" }), "sb_publishable_raw");
  assert.equal(publishableKey({}), "");
});

test("publicSupabaseUrl skips an internal URL for the request's own host", () => {
  const headers = new Headers({ host: "ref.supabase.co" });
  assert.equal(publicSupabaseUrl({ SUPABASE_URL: "https://ref.supabase.co/" }, headers), "https://ref.supabase.co");
  assert.equal(publicSupabaseUrl({ SUPABASE_URL: "http://kong:8000" }, headers), "https://ref.supabase.co");
  assert.equal(publicSupabaseUrl({}, new Headers({ host: "localhost:8080" })), "");
  assert.equal(publicSupabaseUrl({ PUBLIC_SUPABASE_URL: "https://x.supabase.co" }, headers), "https://x.supabase.co");
});

test("renderPage inlines the helpers and a config that cannot close the script tag", () => {
  const html = renderPage(
    "<script>/*__ALERTS__*/\nconst CONFIG = /*__CONFIG__*/null;</script>",
    "export function f() {}\n",
    { brand: "</script><b>" },
  );
  assert.ok(html.includes("function f() {}"));
  assert.ok(!html.includes("export function"));
  assert.ok(html.includes('"brand":"\\u003c/script>\\u003cb>"'));
});

test("the template has both placeholders", () => {
  const template = readFileSync(new URL("./overlay.html", import.meta.url), "utf8");
  assert.ok(template.includes("/*__ALERTS__*/"));
  assert.ok(template.includes("/*__CONFIG__*/null"));
});

test("the handler serves the page and a health check", async () => {
  process.env.SUPABASE_URL = "https://ref.supabase.co";
  process.env.SUPABASE_ANON_KEY = "anon";
  const page = await handler.fetch(new Request("http://localhost/"));
  assert.equal(page.status, 200);
  const html = await page.text();
  assert.ok(html.includes('"supabaseUrl":"https://ref.supabase.co"'));
  assert.ok(html.includes("function paidTip"));

  const health = await (await handler.fetch(new Request("http://localhost/health"))).json();
  assert.equal(health.realtime_configured, true);
  assert.equal((await handler.fetch(new Request("http://localhost/nope"))).status, 404);
});

test("overlayConfig reads the campaign and brand from the environment", () => {
  const config = overlayConfig({ SUPARADE_CAMPAIGN_ID: CAMPAIGN, SPONSOR_BRAND: "Gatorade" }, new Headers({ host: "ref.supabase.co" }));
  assert.equal(config.campaignId, CAMPAIGN);
  assert.equal(config.brand, "Gatorade");
  assert.equal(config.supabaseUrl, "https://ref.supabase.co");
});
