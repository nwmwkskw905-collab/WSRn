export type BackendStatus = "starting" | "online" | "offline" | "error";

export interface RuntimeResponse<T = any> {
  ok: boolean;
  status: number;
  data: T | null;
  error?: string;
}

export interface AppInfo {
  version: string;
  platform: string;
  arch: string;
  dataDir: string;
  isPackaged: boolean;
  backend: { status: BackendStatus; port: number | null; error?: string; python?: string };
  floating: boolean;
  autoLaunch: boolean;
  secure: { contextIsolation: true; nodeIntegration: false; sandbox: true };
}

export interface UpdateInfo {
  current: string;
  latest: string | null;
  updateAvailable: boolean;
  url: string;
  publishedAt?: string;
  notes?: string;
  signature: string;
  error?: string;
}

export interface JarvisBridge {
  request<T = any>(method: string, path: string, body?: unknown): Promise<RuntimeResponse<T>>;
  info(): Promise<AppInfo>;
  restartBackend(): Promise<{ ok: boolean; error?: string }>;
  setFloating(enabled: boolean): Promise<boolean>;
  setAlwaysOnTop(enabled: boolean): Promise<boolean>;
  minimize(): Promise<void>;
  close(): Promise<void>;
  getAutoLaunch(): Promise<boolean>;
  setAutoLaunch(enabled: boolean): Promise<boolean>;
  openExternal(url: string): Promise<{ ok: boolean; error?: string }>;
  checkUpdates(): Promise<UpdateInfo>;
  pickFolder(): Promise<string | null>;
  onBackendStatus(callback: (status: AppInfo["backend"]) => void): () => void;
  onFloating(callback: (enabled: boolean) => void): () => void;
}
