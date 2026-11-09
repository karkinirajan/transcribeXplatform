// Which URLs the desktop window may open or navigate to. Kept free of Electron imports so it can be tested with plain Node.

/** A link that may be handed to the operating system's browser: web pages only. */
function isSafeExternalUrl(raw) {
  try {
    const url = new URL(raw);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

/** The app's own page: the local Next.js server. Anything else must not load inside the app window. */
function isAppUrl(raw, port) {
  try {
    const url = new URL(raw);
    return url.protocol === "http:" && url.hostname === "127.0.0.1" && url.port === String(port) && url.username === "" && url.password === "";
  } catch {
    return false;
  }
}

module.exports = { isSafeExternalUrl, isAppUrl };
