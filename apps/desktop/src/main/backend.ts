import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { app } from "electron";
import type { AppInfo, BackendStatus } from "../shared/contracts";

type StatusListener = (status: AppInfo["backend"]) => void;

export class BackendManager {
  private child: ChildProcessWithoutNullStreams | null = null;
  private port = 8765;
  private status: BackendStatus = "offline";
  private error: string | undefined;
  private token = "";
  private listeners = new Set<StatusListener>();
  private stopping = false;

  readonly dataDir: string;

  constructor() {
    this.dataDir = process.env.JARVIS_DATA_DIR || app.getPath("userData");
    fs.mkdirSync(this.dataDir, { recursive: true });
    fs.mkdirSync(path.join(this.dataDir, "logs"), { recursive: true });
  }

  get currentStatus(): AppInfo["backend"] {
    return { status: this.status, port: this.port, error: this.error, python: this.resolveRuntime().display };
  }

  onStatus(listener: StatusListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(): void {
    for (const listener of this.listeners) listener(this.currentStatus);
  }

  private setStatus(status: BackendStatus, error?: string): void {
    this.status = status;
    this.error = error;
    this.emit();
  }

  private resolveRuntime(): { command: string; args: string[]; cwd?: string; display: string } {
    const exeName = process.platform === "win32" ? "jarvis-agent-runtime.exe" : "jarvis-agent-runtime";
    const bundled = path.join(process.resourcesPath, "backend", exeName);
    if (app.isPackaged && fs.existsSync(bundled)) {
      return { command: bundled, args: [], display: "bundled" };
    }
    if (fs.existsSync(bundled)) {
      return { command: bundled, args: [], display: "bundled-dev" };
    }
    const repo = path.resolve(__dirname, "../../../..");
    const runtimeDir = path.join(repo, "services", "agent-runtime");
    const venvPython =
      process.platform === "win32"
        ? path.join(repo, ".venv", "Scripts", "python.exe")
        : path.join(repo, ".venv", "bin", "python");
    const python = process.env.JARVIS_PYTHON || (fs.existsSync(venvPython) ? venvPython : process.platform === "win32" ? "python" : "python3");
    return {
      command: python,
      args: ["-m", "uvicorn", "jarvis.main:app", "--host", "127.0.0.1", "--port", String(this.port)],
      cwd: runtimeDir,
      display: python,
    };
  }

  private readToken(): string {
    const tokenPath = path.join(this.dataDir, "runtime-token");
    if (!fs.existsSync(tokenPath)) return "";
    const value = fs.readFileSync(tokenPath, "utf8").trim();
    return value;
  }

  private appendLog(line: string): void {
    try {
      fs.appendFileSync(path.join(this.dataDir, "logs", "backend.log"), `${new Date().toISOString()} ${line}\n`);
    } catch {
      /* logging must never crash the app */
    }
  }

  async start(): Promise<void> {
    if (this.child && this.status === "online") return;
    this.setStatus("starting");
    this.stopping = false;
    const runtime = this.resolveRuntime();
    this.appendLog(`spawn ${runtime.command} ${runtime.args.join(" ")} (cwd=${runtime.cwd ?? "-"})`);
    try {
      this.child = spawn(runtime.command, runtime.args, {
        cwd: runtime.cwd,
        env: {
          ...process.env,
          JARVIS_DATA_DIR: this.dataDir,
          JARVIS_PORT: String(this.port),
          JARVIS_HOST: "127.0.0.1",
          JARVIS_REQUIRE_AUTH: "1",
          PYTHONUNBUFFERED: "1",
        },
        windowsHide: true,
      });
    } catch (error) {
      this.setStatus("error", `Falha ao iniciar backend: ${String(error)}`);
      return;
    }
    this.child.stdout.on("data", (data) => this.appendLog(`[out] ${data.toString().trim()}`));
    this.child.stderr.on("data", (data) => this.appendLog(`[err] ${data.toString().trim()}`));
    this.child.on("exit", (code) => {
      this.appendLog(`backend exited code=${code}`);
      if (!this.stopping) this.setStatus("error", `Backend encerrou (codigo ${code}). Veja os logs.`);
      this.child = null;
    });
    const healthy = await this.waitHealthy(40000);
    if (!healthy) {
      this.setStatus("error", "Backend nao respondeu em 40s. Verifique Python/uvicorn e os logs.");
      return;
    }
    this.token = this.readToken();
    if (!this.token) {
      this.setStatus("error", "Token local ausente; o backend deve cria-lo na primeira execucao.");
      return;
    }
    this.setStatus("online");
  }

  private async waitHealthy(timeoutMs: number): Promise<boolean> {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 2000);
        const response = await fetch(`http://127.0.0.1:${this.port}/health`, { signal: controller.signal });
        clearTimeout(timer);
        if (response.ok) return true;
      } catch {
        /* retry */
      }
      await new Promise((resolve) => setTimeout(resolve, 600));
    }
    return false;
  }

  async request(method: string, apiPath: string, body?: unknown): Promise<{ ok: boolean; status: number; data: any; error?: string }> {
    if (!apiPath.startsWith("/api/")) return { ok: false, status: 400, data: null, error: "Caminho nao permitido" };
    if (this.status !== "online") await this.start();
    if (this.status !== "online") {
      return { ok: false, status: 503, data: null, error: this.error || "Backend offline" };
    }
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 120000);
      const response = await fetch(`http://127.0.0.1:${this.port}${apiPath}`, {
        method,
        headers: {
          Authorization: `Bearer ${this.token}`,
          "Content-Type": "application/json",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      clearTimeout(timer);
      const text = await response.text();
      let data: any = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = { raw: text };
      }
      if (response.status === 401) {
        this.token = this.readToken();
      }
      return { ok: response.ok, status: response.status, data, error: response.ok ? undefined : data?.detail || `HTTP ${response.status}` };
    } catch (error) {
      return { ok: false, status: 0, data: null, error: `Falha de comunicacao: ${String(error)}` };
    }
  }

  async restart(): Promise<{ ok: boolean; error?: string }> {
    await this.stop();
    await this.start();
    return { ok: this.status === "online", error: this.error };
  }

  async stop(): Promise<void> {
    this.stopping = true;
    if (!this.child) {
      this.setStatus("offline");
      return;
    }
    const child = this.child;
    child.kill();
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        try {
          child.kill("SIGKILL");
        } catch {
          /* ignore */
        }
        resolve();
      }, 4000);
      child.once("exit", () => {
        clearTimeout(timer);
        resolve();
      });
    });
    this.child = null;
    this.setStatus("offline");
  }
}
