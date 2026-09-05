/*
 * Meta Pixel setup + our own event mirror.
 *
 * Why two things fire on every event?
 * 1. fbq(...) → the REAL Meta Pixel, used by Facebook for ads retargeting
 *    and conversion tracking. Needs a real Pixel ID from Facebook Events
 *    Manager (currently a placeholder, see .env → META_PIXEL_ID).
 * 2. track(...) → sends the same event to OUR OWN backend (/api/track),
 *    which is what powers the Admin Dashboard. We do this because pulling
 *    real numbers back out of Facebook needs the separate Marketing API +
 *    business verification — out of scope for the demo. This gives you a
 *    working, real analytics dashboard today.
 */

let PIXEL_ID = "";

async function initPixel() {
  try {
    const res = await fetch("/api/config");
    const cfg = await res.json();
    PIXEL_ID = cfg.pixel_id;
  } catch (e) {
    console.warn("Could not load pixel config", e);
  }

  if (PIXEL_ID && PIXEL_ID !== "YOUR_PIXEL_ID") {
    /* eslint-disable */
    !function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
    n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;
    n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
    t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,
    document,'script','https://connect.facebook.net/en_US/fbevents.js');
    fbq('init', PIXEL_ID);
    fbq('track', 'PageView');
    /* eslint-enable */
  } else {
    console.info("[Pixel] No real META_PIXEL_ID set yet — Facebook Pixel is inactive. Internal event tracking still works.");
  }

  trackEvent("PageView", { page: location.pathname });
}

function trackEvent(eventName, meta = {}) {
  // 1. Real Meta Pixel (if configured)
  if (window.fbq) {
    try { fbq('track', eventName, meta); } catch (e) {}
  }
  // 2. Our own event log → admin dashboard
  fetch("/api/track", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_name: eventName,
      page: location.pathname,
      product_id: meta.product_id || null,
      meta,
    }),
  }).catch(() => {});
}

document.addEventListener("DOMContentLoaded", initPixel);
