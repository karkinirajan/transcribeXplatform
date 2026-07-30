#!/usr/bin/env node
/**
 * Build the Next.js frontend into a fully self-contained bundle.
 *
 * `output: "standalone"` gives us .next/standalone/server.js with a minimal
 * node_modules, but Next deliberately leaves out `public/` and `.next/static/`
 * (they're normally served by a CDN). The desktop app has no CDN, so we copy
 * them in — after this the standalone directory is the whole frontend.
 *
 * Written in Node rather than shell so the same command works on Windows.
 *
 *   node scripts/build_frontend.mjs [--skip-build]
 */

import { spawnSync } from "node:child_process";
import { cp, rm, stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FRONTEND = path.join(ROOT, "frontend");
const STANDALONE = path.join(FRONTEND, ".next", "standalone");

const skipBuild = process.argv.includes("--skip-build");

function run(command, args, cwd) {
  console.log(`  $ ${command} ${args.join(" ")}`);
  const result = spawnSync(command, args, {
    cwd,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (result.status !== 0) {
    throw new Error(`${command} exited with code ${result.status}`);
  }
}

async function directorySize(dir) {
  let total = 0;
  const { readdir } = await import("node:fs/promises");
  const entries = await readdir(dir, { withFileTypes: true, recursive: true });
  for (const entry of entries) {
    if (entry.isFile()) {
      const full = path.join(entry.parentPath ?? entry.path, entry.name);
      total += (await stat(full)).size;
    }
  }
  return (total / 1024 / 1024).toFixed(1);
}

async function main() {
  console.log("Building Next.js frontend (standalone)");

  if (!existsSync(path.join(FRONTEND, "node_modules"))) {
    console.log("\n[1/3] Installing frontend dependencies…");
    run("npm", ["ci", "--no-audit", "--no-fund"], FRONTEND);
  } else {
    console.log("\n[1/3] Dependencies already installed");
  }

  if (!skipBuild) {
    console.log("\n[2/3] next build…");
    // A stale .next/standalone would otherwise leave dead files in the bundle.
    await rm(STANDALONE, { recursive: true, force: true });
    run("npm", ["run", "build"], FRONTEND);
  } else {
    console.log("\n[2/3] Skipping next build (--skip-build)");
  }

  if (!existsSync(path.join(STANDALONE, "server.js"))) {
    throw new Error(
      `No server.js at ${STANDALONE}. Is output: "standalone" still set in next.config.ts?`
    );
  }

  console.log("\n[3/3] Copying public/ and .next/static/ into the bundle…");
  await cp(path.join(FRONTEND, "public"), path.join(STANDALONE, "public"), {
    recursive: true,
    force: true,
  });
  await cp(
    path.join(FRONTEND, ".next", "static"),
    path.join(STANDALONE, ".next", "static"),
    { recursive: true, force: true }
  );

  const size = await directorySize(STANDALONE);
  console.log(`\n✓ Frontend bundle ready: ${STANDALONE} (${size} MB)`);
}

main().catch((error) => {
  console.error(`\n✗ ${error.message}`);
  process.exit(1);
});
