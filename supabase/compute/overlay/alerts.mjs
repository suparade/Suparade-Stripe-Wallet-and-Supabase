// Pure helpers for the overlay page. page.mjs inlines this file into the page; overlay.test.mjs
// tests it. No imports and no DOM.

export function formatAmount(cents, currency = "usd") {
  const value = Number(cents) / 100;
  const code = String(currency || "usd").toUpperCase();
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: code }).format(value);
  } catch {
    return `${value.toFixed(2)} ${code}`;
  }
}

// The tip to announce for a Realtime change on public.tips, or null. Only paid tips, each once,
// and only for the chosen campaign when there is one.
export function paidTip(payload, campaignId, shown) {
  const tip = payload && payload.new;
  if (!tip || tip.status !== "paid" || !tip.id) return null;
  if (campaignId && tip.campaign_id !== campaignId) return null;
  if (shown && shown.has(tip.id)) return null;
  return tip;
}

export function alertView(tip, creatorName, brand) {
  return {
    amount: formatAmount(tip.amount_cents, tip.currency),
    headline: `${brand || "A sponsor"} tipped ${creatorName || "the streamer"}`,
    message: tip.message || "",
  };
}
