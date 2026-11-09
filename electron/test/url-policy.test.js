const test = require("node:test");
const assert = require("node:assert/strict");
const { isSafeExternalUrl, isAppUrl } = require("../url-policy");

test("web links may be opened in the user's browser", () => {
  for (const url of ["https://www.assemblyai.com/dashboard/signup", "http://example.com/a?b=c", "HTTPS://EXAMPLE.COM"]) {
    assert.equal(isSafeExternalUrl(url), true, url);
  }
});

test("nothing else may be handed to the operating system", () => {
  for (const url of [
    "file:///etc/passwd",
    "file:///C:/Windows/System32/calc.exe",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "smb://attacker/share",
    "ssh://attacker/",
    "vscode://file/x",
    "ms-msdt:/id PCWDiagnostic",
    "steam://run/1",
    "mailto:a@b.co",
    "tel:+1",
    "about:blank",
    "blob:http://127.0.0.1:3000/x",
    "ftp://example.com/",
    "//example.com/x",
    "/relative/path",
    "not a url",
    "",
  ]) {
    assert.equal(isSafeExternalUrl(url), false, url);
  }
});

test("non-strings are refused", () => {
  for (const value of [undefined, null, 5, {}, []]) assert.equal(isSafeExternalUrl(value), false);
});

test("the app's own page is the local server on its port, over http, with no credentials", () => {
  assert.equal(isAppUrl("http://127.0.0.1:3000", 3000), true);
  assert.equal(isAppUrl("http://127.0.0.1:3000/", 3000), true);
  assert.equal(isAppUrl("http://127.0.0.1:3000/some/page?x=1#y", 3000), true);
});

test("every other page is not the app", () => {
  for (const url of [
    "http://127.0.0.1:3001/",
    "http://127.0.0.1/",
    "https://127.0.0.1:3000/",
    "http://localhost:3000/",
    "http://127.0.0.1.evil.example:3000/",
    "http://evil.example/",
    "http://user@127.0.0.1:3000/",
    "http://user:pw@127.0.0.1:3000/",
    "http://127.0.0.1:3000@evil.example/",
    "file:///index.html",
    "javascript:alert(1)",
    "not a url",
    "",
  ]) {
    assert.equal(isAppUrl(url, 3000), false, url);
  }
});

test("the port is compared as a number or as text", () => {
  assert.equal(isAppUrl("http://127.0.0.1:3000/", "3000"), true);
  assert.equal(isAppUrl("http://127.0.0.1:3000/", 8000), false);
});
