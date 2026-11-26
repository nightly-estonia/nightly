import { pbkdf2Sync, timingSafeEqual } from "node:crypto";
import { getStore } from "@netlify/blobs";

const headers = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Access-Control-Allow-Origin": "https://nightlyest.netlify.app",
};
const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers });

const estonianDay = (timestamp) =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Tallinn",
    year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date(timestamp));
const recentDays = (count) =>
  Array.from({ length: count }, (_, i) =>
    estonianDay(Date.now() - (count - 1 - i) * 86400000));

export default async function (request) {
  if (request.method !== "GET" && request.method !== "POST") {
    return json({ error: "Method not allowed" }, 405);
  }
  try {
    const store = getStore("nightly-anonymous-visits-v1");
    if (request.method === "POST") {
      const origin = request.headers.get("origin");
      // Only our Netlify website should send tracking events.
      if (origin && origin !== "https://nightlyest.netlify.app") {
        return json({ error: "Forbidden" }, 403);
      }
      const payload = await request.json().catch(() => null);
      const id = payload?.id;
      if (typeof id !== "string" || !/^[a-f0-9-]{36}$/i.test(id)) {
        return json({ error: "Invalid visit ID" }, 400);
      }
      const now = new Date().toISOString();
      const day = estonianDay(now);
      // A new ID is generated for each page load; heartbeats reuse the same ID.
      await store.setJSON(`visits/${day}/${id}`, { lastSeen: now });
      return json({ ok: true });
    }

    // Password is never stored in the repository. Only the salted,
    // deliberately expensive derived key is committed.
    const provided = request.headers.get("X-Nightly-Statistics-Password") || "";
    const expected = Buffer.from("64ac6782290ab97319826d457e49f3abade646bd310398f76e9137bd8737ba7b", "hex");
    let authorized = false;
    if (provided.length > 0 && provided.length < 150) {
      const result = pbkdf2Sync(provided, Buffer.from("f69d2ab4fa5973ddc43bfce037eef0c1", "hex"), 210000, 32, "sha256");
      authorized = timingSafeEqual(result, expected);
    }
    if (!authorized) return json({ error: "Vale parool või parool puudub." }, 401);

    const { blobs } = await store.list({ prefix: "visits/" });
    const dates = recentDays(7);
    const counts = Object.fromEntries(dates.map((date) => [date, 0]));
    let today = 0;
    let last7 = 0;
    let total = 0;
    const todayDate = dates[6];
    const yesterday = estonianDay(Date.now() - 86400000);
    const activeKeys = [];
    for (const blob of blobs) {
      const day = blob.key.split("/")[1];
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) continue;
      total++;
      if (day === todayDate) today++;
      if (day in counts) { counts[day]++; last7++; }
      if (day === todayDate || day === yesterday) activeKeys.push(blob.key);
    }
    const cutoff = Date.now() - 5 * 60 * 1000;
    let active = 0;
    // Limit expensive per-visit lookups on a busy site. The active count is an estimate.
    const currentKeys = activeKeys.slice(-250);
    const results = await Promise.all(currentKeys.map((key) => store.getJSON(key).catch(() => null)));
    for (const item of results) {
      if (item?.lastSeen && Date.parse(item.lastSeen) > cutoff) active++;
    }
    return json({
      today, last7, total, active,
      activeApproximate: activeKeys.length > 250,
      days: dates.map((date) => ({ date, visits: counts[date] })),
      updatedAt: new Date().toISOString(),
      notes: "Counts are page loads, not unique people. Active = page loads sending heartbeats in the last five minutes.",
    });
  } catch (error) {
    console.error("Nightly statistics error:", error);
    return json({ error: "Statistika ei ole veel saadaval. Kontrolli Netlify funktsiooni avaldamist." }, 503);
  }
}
