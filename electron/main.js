const { app, BrowserWindow, Menu, dialog, shell } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const API_PORT = 8000;
const NEXT_PORT = 3000;
const IS_DEV = process.env.NODE_ENV === "development" || !app.isPackaged;
const IS_WINDOWS = process.platform === "win32";

// Packaged: everything lives under process.resourcesPath.
// Dev: everything is read straight out of the repo.
const REPO_ROOT = path.join(__dirname, "..");
const RESOURCES = app.isPackaged ? process.resourcesPath : REPO_ROOT;

// scripts/bundle_runtime.py and scripts/fetch_ffmpeg.py write here.
const RUNTIME_DIR = app.isPackaged
  ? path.join(RESOURCES, "runtime")
  : path.join(REPO_ROOT, "build", "runtime");

// scripts/build_frontend.mjs produces the standalone Next.js server.
const FRONTEND_DIR = app.isPackaged
  ? path.join(RESOURCES, "frontend")
  : path.join(REPO_ROOT, "frontend", ".next", "standalone");

let startupError = null;

// ---------------------------------------------------------------------------
// Bundled runtime resolution
// ---------------------------------------------------------------------------

/**
 * Locate the Python interpreter shipped inside the app. Falls back to a system
 * interpreter so a dev checkout without build/runtime still runs.
 */
function resolvePython() {
  const bundled = IS_WINDOWS
    ? path.join(RUNTIME_DIR, "python", "python.exe")
    : path.join(RUNTIME_DIR, "python", "bin", "python3");

  if (fs.existsSync(bundled)) return { command: bundled, bundled: true };

  console.warn(`[api] No bundled interpreter at ${bundled}; falling back to system Python`);
  return { command: IS_WINDOWS ? "python" : "python3", bundled: false };
}

/**
 * Prepend the bundled ffmpeg/ffprobe directory to PATH. The transcription
 * pipeline shells out to both; if they were not bundled the app transparently
 * uses whatever is already on PATH.
 */
function buildPath() {
  const binDir = path.join(RUNTIME_DIR, "bin");
  const current = process.env.PATH || "";
  return fs.existsSync(binDir) ? `${binDir}${path.delimiter}${current}` : current;
}

// ---------------------------------------------------------------------------
// Backend process management
// ---------------------------------------------------------------------------
let apiProcess = null;
const apiLog = [];

function recordApiLog(chunk) {
  // Keep a small ring buffer so a crash dialog can show why it failed.
  apiLog.push(chunk.toString());
  if (apiLog.length > 50) apiLog.shift();
}

/**
 * The install directory is read-only, so API keys live in the per-user config
 * directory. Seed it from .env.example on first run so there is something to
 * edit, and return the path for the backend to load.
 */
function ensureConfigDir() {
  const configDir = app.getPath("userData");
  const envFile = path.join(configDir, ".env");

  if (!fs.existsSync(envFile)) {
    try {
      fs.mkdirSync(configDir, { recursive: true });
      const template = path.join(RESOURCES, ".env.example");
      if (fs.existsSync(template)) {
        fs.copyFileSync(template, envFile);
        console.log(`[config] Seeded ${envFile} from .env.example`);
      }
    } catch (err) {
      console.error(`[config] Could not create ${envFile}: ${err.message}`);
    }
  }

  return configDir;
}

function startApiServer() {
  // In dev the API is already running — `npm run dev` starts it with uv via
  // concurrently. Starting a second one here would just fail on a busy port.
  if (IS_DEV) {
    console.log("[api] Dev mode — expecting an API server on :" + API_PORT);
    return;
  }

  const backendDir = path.join(RESOURCES, "backend");
  const { command, bundled } = resolvePython();
  const configDir = ensureConfigDir();

  console.log(`[api] Starting with ${bundled ? "bundled" : "system"} Python: ${command}`);
  console.log(`[api] Config directory: ${configDir}`);

  apiProcess = spawn(
    command,
    ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", String(API_PORT)],
    {
      cwd: backendDir,
      env: {
        ...process.env,
        PATH: buildPath(),
        PYTHONPATH: path.join(RESOURCES, "utilities_data", "transcribe"),
        PYTHONUNBUFFERED: "1",
        TRANSCRIBE_CONFIG_DIR: configDir,
      },
      stdio: ["ignore", "pipe", "pipe"],
    }
  );

  apiProcess.stdout.on("data", (d) => {
    recordApiLog(d);
    process.stdout.write(`[api] ${d}`);
  });
  apiProcess.stderr.on("data", (d) => {
    recordApiLog(d);
    process.stderr.write(`[api] ${d}`);
  });

  apiProcess.on("error", (err) => {
    startupError = `Failed to start the transcription service: ${err.message}`;
    console.error("[api]", startupError);
  });

  apiProcess.on("close", (code) => {
    if (code !== 0 && !app.isQuitting) {
      console.error(`[api] Exited with code ${code}`);
    }
  });
}

function stopApiServer() {
  if (apiProcess) {
    apiProcess.kill("SIGTERM");
    apiProcess = null;
  }
}

// ---------------------------------------------------------------------------
// Next.js server — run the standalone bundle with Electron's own Node
// ---------------------------------------------------------------------------
let nextProcess = null;

function startNextServer() {
  if (IS_DEV) return; // started externally by `npm run dev`

  const server = path.join(FRONTEND_DIR, "server.js");
  if (!fs.existsSync(server)) {
    startupError = `Frontend bundle missing at ${server}. Run: node scripts/build_frontend.mjs`;
    console.error("[next]", startupError);
    return;
  }

  // ELECTRON_RUN_AS_NODE turns process.execPath into a plain Node binary, so
  // the packaged app needs no Node.js or npm installed on the machine.
  nextProcess = spawn(process.execPath, [server], {
    cwd: FRONTEND_DIR,
    env: {
      ...process.env,
      ELECTRON_RUN_AS_NODE: "1",
      NODE_ENV: "production",
      PORT: String(NEXT_PORT),
      HOSTNAME: "127.0.0.1",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  nextProcess.stdout.on("data", (d) => process.stdout.write(`[next] ${d}`));
  nextProcess.stderr.on("data", (d) => process.stderr.write(`[next] ${d}`));
  nextProcess.on("error", (err) => {
    startupError = `Failed to start the UI server: ${err.message}`;
    console.error("[next]", startupError);
  });
}

function stopNextServer() {
  if (nextProcess) {
    nextProcess.kill("SIGTERM");
    nextProcess = null;
  }
}

// ---------------------------------------------------------------------------
// Wait for a local server to answer
// ---------------------------------------------------------------------------
function waitForPort(port, pathname, timeout = 60000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();

    const check = () => {
      const req = http.get({ host: "127.0.0.1", port, path: pathname }, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode < 500) resolve();
        else retry();
      });
      req.on("error", retry);
      req.setTimeout(1000, () => {
        req.destroy();
        retry();
      });
    };

    const retry = () => {
      if (Date.now() - start > timeout) {
        reject(new Error(`127.0.0.1:${port} did not respond within ${timeout / 1000}s`));
      } else {
        setTimeout(check, 300);
      }
    };

    check();
  });
}

// ---------------------------------------------------------------------------
// Main window
// ---------------------------------------------------------------------------
let mainWindow = null;

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 960,
    height: 720,
    minWidth: 720,
    minHeight: 560,
    show: false,
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "default",
    backgroundColor: "#0a0a0a",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // External links belong in the user's browser, not in an app window.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  await mainWindow.loadURL(`http://127.0.0.1:${NEXT_PORT}`);

  if (IS_DEV) mainWindow.webContents.openDevTools({ mode: "detach" });
}

// ---------------------------------------------------------------------------
// Menu — mainly so users can reach the .env file that holds their API keys
// ---------------------------------------------------------------------------
function buildMenu() {
  const isMac = process.platform === "darwin";

  // A packaged install reads keys from the per-user config dir; a dev checkout
  // reads the repo's own .env, which is what `npm run dev` loads.
  const configDir = IS_DEV ? REPO_ROOT : app.getPath("userData");

  const openKeys = {
    label: "Open API Keys File…",
    accelerator: "CmdOrCtrl+,",
    click: async () => {
      const envFile = path.join(configDir, ".env");
      if (!fs.existsSync(envFile)) {
        shell.openPath(configDir);
        return;
      }
      // openPath falls back to revealing the file if no editor is registered.
      const error = await shell.openPath(envFile);
      if (error) shell.showItemInFolder(envFile);
    },
  };

  const template = [
    ...(isMac ? [{ role: "appMenu" }] : []),
    {
      label: "File",
      submenu: [
        openKeys,
        {
          label: "Open Config Folder",
          click: () => shell.openPath(configDir),
        },
        { type: "separator" },
        isMac ? { role: "close" } : { role: "quit" },
      ],
    },
    { role: "editMenu" },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    {
      role: "help",
      submenu: [
        {
          label: "Get API Keys",
          click: () => shell.openExternal("https://www.assemblyai.com/dashboard/signup"),
        },
        {
          label: "Documentation",
          click: () => shell.openExternal("https://github.com/karkinirajan/transcribe"),
        },
      ],
    },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function reportFatal(message) {
  const detail = apiLog.length ? `\n\nLast output:\n${apiLog.slice(-8).join("")}` : "";
  dialog.showErrorBox("Transcribe could not start", `${message}${detail}`);
  app.quit();
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
app.on("ready", async () => {
  buildMenu();
  startApiServer();
  startNextServer();

  try {
    await Promise.all([
      waitForPort(API_PORT, "/api/health"),
      waitForPort(NEXT_PORT, "/"),
    ]);
  } catch (err) {
    reportFatal(startupError || err.message);
    return;
  }

  await createWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (mainWindow === null) createWindow();
});

app.on("before-quit", () => {
  app.isQuitting = true;
  stopApiServer();
  stopNextServer();
});
