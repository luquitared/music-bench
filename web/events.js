// Funnel events go to the Odapt control plane (text/plain JSON: no CORS preflight).
// session_id is an anonymous per-browser id, so uniques can be counted; nothing else identifies anyone.
(function () {
  const EVENTS = "https://api.odapt.ai/events";
  let vid = null;
  try { vid = localStorage.getItem("mb-vid"); if (!vid) localStorage.setItem("mb-vid", vid = crypto.randomUUID()); } catch {}
  const local = /^(localhost|127\.|0\.0\.0\.0|\[::1\])/.test(location.hostname) || location.protocol === "file:";
  window.track = function (type, props) {
    if (local) return console.debug("[track]", type, props || {});
    try {
      const body = JSON.stringify({ app: "music-bench", type, session_id: vid, props: props || {} });
      if (!(navigator.sendBeacon && navigator.sendBeacon(EVENTS, new Blob([body], { type: "text/plain" })))) {
        fetch(EVENTS, { method: "POST", body, keepalive: true, headers: { "content-type": "text/plain" } }).catch(() => {});
      }
    } catch {}
  };
  track("view", { referrer: document.referrer || null, path: location.pathname });
  let deep = false;
  addEventListener("scroll", () => {
    if (deep) return;
    const h = document.documentElement;
    if ((h.scrollTop + innerHeight) / h.scrollHeight > 0.75) { deep = true; track("scroll_deep"); }
  }, { passive: true });
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[href^='http']");
    if (a && a.host !== location.host) track("outbound", { href: a.href });
  });
  const seen = new Set();
  const io = "IntersectionObserver" in window && new IntersectionObserver((es) => es.forEach((x) => {
    if (x.isIntersecting && !seen.has(x.target.id)) { seen.add(x.target.id); track("section_view", { id: x.target.id }); }
  }), { threshold: 0.4 });
  if (io) document.querySelectorAll("section[id]").forEach((s) => io.observe(s));
})();
