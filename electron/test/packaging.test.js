const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

// electron-builder packs only what `files:` lists, so a local module that main.js or preload.js requires and that is missing from
// the list makes the installed app crash at start-up although it runs fine from the repository.
const root = path.join(__dirname, "..");
const builder = fs.readFileSync(path.join(root, "electron-builder.yml"), "utf8");
const listed = new Set(
  (builder.match(/^files:\n((?:[ \t]+- .+\n?)+)/m)?.[1] ?? "")
    .split("\n")
    .map((line) => line.replace(/^\s*-\s*/, "").trim())
    .filter(Boolean),
);

function localRequires(file) {
  const source = fs.readFileSync(path.join(root, file), "utf8");
  return [...source.matchAll(/require\(\s*["'](\.{1,2}\/[^"']+)["']\s*\)/g)].map((m) => path.normalize(m[1]).replace(/(\.js)?$/, ".js"));
}

test("the packaging list is read", () => {
  assert.ok(listed.has("main.js") && listed.has("preload.js"), [...listed].join(", "));
});

for (const entry of ["main.js", "preload.js"]) {
  test(`${entry}: every local module it requires is packaged`, () => {
    for (const required of localRequires(entry)) {
      assert.ok(listed.has(required), `${entry} requires ${required}, which electron-builder.yml does not package`);
      assert.ok(fs.existsSync(path.join(root, required)), `${required} does not exist`);
    }
  });
}

test("main.js does use the URL policy (so the check above has something to guard)", () => {
  assert.ok(localRequires("main.js").includes("url-policy.js"));
});

test("the window is sandboxed, isolated and has no Node integration", () => {
  const source = fs.readFileSync(path.join(root, "main.js"), "utf8");
  assert.match(source, /sandbox:\s*true/);
  assert.match(source, /contextIsolation:\s*true/);
  assert.match(source, /nodeIntegration:\s*false/);
});

test("external links go through the URL policy, never straight to the operating system", () => {
  const source = fs.readFileSync(path.join(root, "main.js"), "utf8");
  const calls = [...source.matchAll(/shell\.openExternal\(([^)]*)\)/g)].map((m) => m[1].trim());
  // the policy-guarded helper, plus the two fixed links in the Help menu
  assert.ok(calls.includes("url"), "the guarded call");
  const guarded = source.match(/if \(isSafeExternalUrl\(url\)\) shell\.openExternal\(url\);/);
  assert.ok(guarded, "the openExternal(url) call must sit behind isSafeExternalUrl");
  for (const call of calls.filter((c) => c !== "url")) assert.match(call, /^"https:\/\//, `an unguarded openExternal(${call})`);
});
