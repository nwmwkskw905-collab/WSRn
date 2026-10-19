import { contextBridge, ipcRenderer } from "electron";
import type { AppInfo, JarvisBridge, RuntimeResponse, UpdateInfo } from "../shared/contracts";

const invoke = <T>(channel: string, ...args: unknown[]): Promise<T> => ipcRenderer.invoke(channel, ...args);

const bridge: JarvisBridge = {
  request: <T = any>(method: string, path: string, body?: unknown) =>
    invoke<RuntimeResponse<T>>("runtime:request", method, path, body),
  info: () => invoke<AppInfo>("app:info"),
  restartBackend: () => invoke<{ ok: boolean; error?: string }>("runtime:restart"),
  setFloating: (enabled: boolean) => invoke<boolean>("window:floating", enabled),
  setAlwaysOnTop: (enabled: boolean) => invoke<boolean>("window:alwaysOnTop", enabled),
  minimize: () => invoke<void>("window:minimize"),
  close: () => invoke<void>("window:close"),
  getAutoLaunch: () => invoke<boolean>("app:autolaunch:get"),
  setAutoLaunch: (enabled: boolean) => invoke<boolean>("app:autolaunch:set", enabled),
  openExternal: (url: string) => invoke<{ ok: boolean; error?: string }>("app:open-external", url),
  checkUpdates: () => invoke<UpdateInfo>("app:check-updates"),
  pickFolder: () => invoke<string | null>("app:pick-folder"),
  onBackendStatus: (callback) => {
    const handler = (_event: unknown, status: AppInfo["backend"]) => callback(status);
    ipcRenderer.on("backend:status", handler);
    return () => ipcRenderer.removeListener("backend:status", handler);
  },
  onFloating: (callback) => {
    const handler = (_event: unknown, enabled: boolean) => callback(enabled);
    ipcRenderer.on("window:floating", handler);
    return () => ipcRenderer.removeListener("window:floating", handler);
  },
};

contextBridge.exposeInMainWorld("jarvis", bridge);
