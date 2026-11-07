// Keeps a Server-Sent Events connection healthy on flaky networks and sleeping phones.
//
// The server sends the full state when a connection opens and a "ping" every 15 seconds,
// so reconnecting always re-syncs us, and silence for too long means the link is dead.

const CONNECTING = 0;
const OPEN = 1;
const PING_EVERY_MS = 15000;
const SILENCE_LIMIT_MS = PING_EVERY_MS * 3;
const MAX_QUICK_RETRIES = 8;

export const STATUS_TEXT = {
  live: "Live",
  reconnecting: "Reconnecting\u2026",
  offline: "You appear to be offline. Waiting for a connection\u2026",
  failed: "Connection lost. Reload the page to continue.",
};

export function statusText(status) {
  return STATUS_TEXT[status] || "";
}

/** Connect to `url`. onState(snapshot) gets every state event; onStatus(name) reports health. */
export function connectLive(url, { onState, onStatus }) {
  let source = null;
  let retryTimer = null;
  let attempts = 0;
  let lastSeen = Date.now();

  const seen = () => { lastSeen = Date.now(); };

  function open() {
    clearTimeout(retryTimer);
    if (source) source.close();
    seen();
    source = new EventSource(url);
    source.addEventListener("state", (event) => { seen(); onState(JSON.parse(event.data)); });
    source.addEventListener("ping", seen);
    source.onopen = () => { attempts = 0; seen(); onStatus("live"); };
    source.onerror = () => {
      if (source.readyState === CONNECTING) onStatus("reconnecting"); // the browser is retrying
      else retryLater(); // closed for good (e.g. the server restarted): reconnect ourselves
    };
  }

  function retryLater() {
    attempts += 1;
    if (attempts > MAX_QUICK_RETRIES) { onStatus("failed"); return; }
    onStatus("reconnecting");
    retryTimer = setTimeout(open, Math.min(15000, 1000 * 2 ** (attempts - 1)));
  }

  // After the tab sleeps or the network changes, a connection can look open but be dead.
  function nudge() {
    const stale = Date.now() - lastSeen > SILENCE_LIMIT_MS / 2;
    if (source && source.readyState === OPEN && !stale) {
      onStatus("live"); // the link survived (e.g. a brief "offline" blip), so clear any warning
    } else {
      attempts = 0;
      open();
    }
  }

  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") nudge(); });
  window.addEventListener("online", nudge);
  window.addEventListener("offline", () => onStatus("offline"));
  setInterval(() => {
    if (Date.now() - lastSeen > SILENCE_LIMIT_MS) { onStatus("reconnecting"); attempts = 0; open(); }
  }, PING_EVERY_MS);

  open();
  return { close() { clearTimeout(retryTimer); if (source) source.close(); } };
}
