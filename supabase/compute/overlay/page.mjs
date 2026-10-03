// Server side of the overlay: finds the public Supabase URL and anon key, and renders the page.

// The browser-safe key. Compute passes the same defaults as Edge Functions; newer projects may
// only have SUPABASE_PUBLISHABLE_KEYS, a JSON object of named keys.
export function publishableKey(env) {
  if (env.SUPABASE_ANON_KEY) return env.SUPABASE_ANON_KEY;
  if (env.SUPABASE_PUBLISHABLE_KEY) return env.SUPABASE_PUBLISHABLE_KEY;
  const raw = env.SUPABASE_PUBLISHABLE_KEYS;
  if (!raw) return "";
  try {
    const keys = JSON.parse(raw);
    if (keys && typeof keys === "object") return keys.default || Object.values(keys)[0] || "";
    return "";
  } catch {
    return raw;
  }
}

// The URL the viewer's browser can reach. An internal SUPABASE_URL is skipped in favour of the host
// the request came in on (<ref>.supabase.co).
export function publicSupabaseUrl(env, headers) {
  if (env.PUBLIC_SUPABASE_URL) return env.PUBLIC_SUPABASE_URL.replace(/\/$/, "");
  if ((env.SUPABASE_URL || "").startsWith("https://")) return env.SUPABASE_URL.replace(/\/$/, "");
  const host = headers?.get?.("x-forwarded-host") || headers?.get?.("host") || "";
  return host.endsWith(".supabase.co") ? `https://${host}` : "";
}

export function overlayConfig(env, headers) {
  return {
    supabaseUrl: publicSupabaseUrl(env, headers),
    anonKey: publishableKey(env),
    campaignId: env.SUPARADE_CAMPAIGN_ID || "",
    brand: env.SPONSOR_BRAND || "Gatorade",
  };
}

export function renderPage(template, alertsSource, config) {
  // "<" escaped so nothing in the config can close the <script> tag.
  const json = JSON.stringify(config).replace(/</g, "\\u003c");
  const helpers = alertsSource.replace(/^export /gm, "");
  return template.replace("/*__ALERTS__*/", () => helpers).replace("/*__CONFIG__*/null", () => json);
}
