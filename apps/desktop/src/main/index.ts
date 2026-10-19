import { app, BrowserWindow, dialog, globalShortcut, ipcMain, Menu, nativeImage, shell, Tray } from "electron";
import fs from "node:fs";
import path from "node:path";
import { BackendManager } from "./backend";
import { checkForUpdates } from "./updater";
import type { AppInfo } from "../shared/contracts";

const APP_VERSION = "0.9.0";
const DEV_URL = process.env.JARVIS_RENDERER_URL;
let mainWindow: BrowserWindow | null = null;
let floatingWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let backend: BackendManager;
let isQuitting = false;

function resourcesPath(...parts: string[]): string {
  return path.join(app.isPackaged ? process.resourcesPath : path.join(__dirname, "../../resources"), ...parts);
}

function preloadPath(): string {
  return path.join(__dirname, "../preload/index.js");
}

function trustedSender(event: Electron.IpcMainInvokeEvent): boolean {
  const url = event.senderFrame?.url || "";
  if (DEV_URL && url.startsWith(DEV_URL)) return true;
  if (url.startsWith("file://")) return true;
  return false;
}

function secureWebPreferences() {
  return {
    preload: preloadPath(),
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: true,
    webSecurity: true,
    spellcheck: false,
  } as const;
}

function hardenWindow(window: BrowserWindow): void {
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) void shell.openExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    const allowed = (DEV_URL && url.startsWith(DEV_URL)) || url.startsWith("file://");
    if (!allowed) event.preventDefault();
  });
  window.webContents.session.setPermissionRequestHandler((_wc, permission, callback, details) => {
    // Apenas microfone para o proprio renderer. Camera, geolocalizacao, notificacoes e
    // qualquer outra permissao permanecem negadas por padrao.
    const origin = details.requestingUrl || "";
    const trusted = (DEV_URL && origin.startsWith(DEV_URL)) || origin.startsWith("file://");
    const mediaTypes = "mediaTypes" in details ? details.mediaTypes || [] : [];
    callback(permission === "media" && trusted && mediaTypes.every((type: string) => type === "audio"));
  });
  window.webContents.on("will-attach-webview", (event) => event.preventDefault());
}

function loadRenderer(window: BrowserWindow): void {
  if (DEV_URL) {
    void window.loadURL(DEV_URL);
  } else {
    void window.loadFile(path.join(__dirname, "../../dist/renderer/index.html"));
  }
}

function createMainWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1080,
    minHeight: 700,
    backgroundColor: "#05070a",
    show: false,
    icon: resourcesPath("icon.png"),
    title: "JARVIS AI",
    webPreferences: secureWebPreferences(),
  });
  hardenWindow(window);
  loadRenderer(window);
  window.once("ready-to-show", () => window.show());
  window.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      window.hide();
    }
  });
  window.on("closed", () => {
    mainWindow = null;
  });
  return window;
}

function createFloatingWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 420,
    height: 600,
    minWidth: 360,
    minHeight: 480,
    resizable: true,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: false,
    backgroundColor: "#05070a",
    show: false,
    icon: resourcesPath("icon.png"),
    webPreferences: secureWebPreferences(),
  });
  hardenWindow(window);
  loadRenderer(window);
  window.once("ready-to-show", () => {
    window.show();
    window.webContents.send("window:floating", true);
  });
  window.on("closed", () => {
    floatingWindow = null;
  });
  return window;
}

function toggleFloating(enabled: boolean): boolean {
  if (enabled) {
    if (!floatingWindow) floatingWindow = createFloatingWindow();
    floatingWindow.show();
    floatingWindow.setAlwaysOnTop(true);
    mainWindow?.hide();
  } else {
    floatingWindow?.close();
    floatingWindow = null;
    mainWindow?.show();
    mainWindow?.focus();
    mainWindow?.webContents.send("window:floating", false);
  }
  return enabled;
}

async function createTray(): Promise<void> {
  const iconPath = resourcesPath("tray.png");
  if (!fs.existsSync(iconPath)) return;
  tray = new Tray(nativeImage.createFromPath(iconPath));
  tray.setToolTip("JARVIS AI");
  const rebuild = () =>
    tray?.setContextMenu(
      Menu.buildFromTemplate([
        { label: "Abrir JARVIS", click: () => { mainWindow?.show(); mainWindow?.focus(); } },
        { label: "Modo flutuante", click: () => toggleFloating(true) },
        { type: "separator" },
        {
          label: "PARAR JARVIS",
          click: async () => {
            await backend.request("POST", "/api/security/stop", { reason: "Tray PARAR JARVIS" });
            mainWindow?.webContents.send("backend:status", backend.currentStatus);
          },
        },
        { label: "Reiniciar backend", click: () => void backend.restart() },
        { type: "separator" },
        { label: "Sair", click: () => { isQuitting = true; app.quit(); } },
      ]),
    );
  rebuild();
  tray.on("click", () => { mainWindow?.show(); mainWindow?.focus(); });
}

function registerIpc(): void {
  const guard = <T>(event: Electron.IpcMainInvokeEvent, fn: () => Promise<T> | T): Promise<T> => {
    if (!trustedSender(event)) return Promise.reject(new Error("Origem IPC nao autorizada"));
    return Promise.resolve(fn());
  };

  ipcMain.handle("runtime:request", (event, method: string, apiPath: string, body?: unknown) =>
    guard(event, () => backend.request(String(method), String(apiPath), body)),
  );
  ipcMain.handle("runtime:health", (event) => guard(event, () => backend.request("GET", "/api/status")));
  ipcMain.handle("runtime:restart", (event) => guard(event, () => backend.restart()));
  ipcMain.handle("app:info", (event) =>
    guard<AppInfo>(event, () => ({
      version: APP_VERSION,
      platform: process.platform,
      arch: process.arch,
      dataDir: backend.dataDir,
      isPackaged: app.isPackaged,
      backend: backend.currentStatus,
      floating: Boolean(floatingWindow),
      autoLaunch: app.getLoginItemSettings().openAtLogin,
      secure: { contextIsolation: true, nodeIntegration: false, sandbox: true },
    })),
  );
  ipcMain.handle("window:minimize", (event) => guard(event, () => { BrowserWindow.fromWebContents(event.sender)?.minimize(); }));
  ipcMain.handle("window:close", (event) => guard(event, () => { BrowserWindow.fromWebContents(event.sender)?.hide(); }));
  ipcMain.handle("window:floating", (event, enabled: boolean) => guard(event, () => toggleFloating(Boolean(enabled))));
  ipcMain.handle("window:alwaysOnTop", (event, enabled: boolean) =>
    guard(event, () => {
      const window = BrowserWindow.fromWebContents(event.sender);
      window?.setAlwaysOnTop(Boolean(enabled));
      return Boolean(enabled);
    }),
  );
  ipcMain.handle("app:autolaunch:get", (event) => guard(event, () => app.getLoginItemSettings().openAtLogin));
  ipcMain.handle("app:autolaunch:set", (event, enabled: boolean) =>
    guard(event, () => {
      app.setLoginItemSettings({ openAtLogin: Boolean(enabled), args: [] });
      return app.getLoginItemSettings().openAtLogin;
    }),
  );
  ipcMain.handle("app:open-external", (event, url: string) =>
    guard(event, async () => {
      if (!/^https:\/\//i.test(url)) return { ok: false, error: "Apenas URLs https sao permitidas" };
      await shell.openExternal(url);
      return { ok: true };
    }),
  );
  ipcMain.handle("app:check-updates", (event) => guard(event, () => checkForUpdates(APP_VERSION)));
  ipcMain.handle("app:pick-folder", (event) =>
    guard(event, async () => {
      const result = await dialog.showOpenDialog({ properties: ["openDirectory", "createDirectory"] });
      return result.canceled ? null : result.filePaths[0] || null;
    }),
  );
}

app.on("second-instance", () => {
  mainWindow?.show();
  mainWindow?.focus();
});

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.whenReady().then(async () => {
    backend = new BackendManager();
    backend.onStatus((status) => {
      for (const window of BrowserWindow.getAllWindows()) window.webContents.send("backend:status", status);
    });
    registerIpc();
    await backend.start();
    mainWindow = createMainWindow();
    await createTray();
    globalShortcut.register("CommandOrControl+Shift+J", () => {
      if (floatingWindow) toggleFloating(false);
      else {
        mainWindow?.show();
        mainWindow?.focus();
      }
    });
    app.on("activate", () => {
      if (!mainWindow) mainWindow = createMainWindow();
      mainWindow.show();
    });
  });
}

app.on("before-quit", () => {
  isQuitting = true;
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
  void backend?.stop();
});

app.on("window-all-closed", () => {
  // Tray application: keep the runtime alive until explicit quit.
  if (process.platform !== "darwin" && isQuitting) app.quit();
});
