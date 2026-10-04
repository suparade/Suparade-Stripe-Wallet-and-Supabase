// Suparade stream overlay on Supabase Compute: the page a streamer adds to OBS as a browser source.
// The page subscribes to Supabase Realtime and shows each tip the moment it is paid.
// Deploy: supabase compute deploy overlay --project-ref <ref>
// Page:   https://<ref>.supabase.co/compute/v1/overlay  (?campaign=<id>&brand=<name>&test&debug)
import { readFileSync } from "node:fs";
import { overlayConfig, renderPage } from "./page.mjs";

const TEMPLATE = readFileSync(new URL("./overlay.html", import.meta.url), "utf8");
const ALERTS = readFileSync(new URL("./alerts.mjs", import.meta.url), "utf8");

export default {
  fetch(request) {
    const { pathname } = new URL(request.url);
    const config = overlayConfig(process.env, request.headers);
    if (pathname === "/health") {
      return Response.json({
        ok: true,
        realtime_configured: Boolean(config.supabaseUrl && config.anonKey),
        campaign_id: config.campaignId || null,
      });
    }
    if (pathname === "/" || pathname === "") {
      return new Response(renderPage(TEMPLATE, ALERTS, config), {
        headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
      });
    }
    return new Response("Not found", { status: 404 });
  },
};
