import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";

export type Tone = "neutral" | "good" | "warn" | "bad" | "info";

const ICONS: Record<string, string> = {
  home: "M3 11.5 12 4l9 7.5M5 10v10h5v-6h4v6h5V10",
  chat: "M4 5h16v11H8l-4 4V5z",
  voice: "M12 4a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3M8 21h8",
  computer: "M3 5h18v11H3zM8 20h8M12 16v4",
  tasks: "M5 6h3v3H5zM5 15h3v3H5zM11 7h9M11 16h9M5 10.5h3",
  agents: "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM16 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM2 20c0-3 2.5-5 6-5s6 2 6 5M14 20c0-2 1.5-3.5 4-3.5",
  research: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM16 16l5 5",
  business: "M3 20V9l6-4v15M9 20V5l6 4v11M15 20v-7l6 3v4M3 20h18",
  sales: "M4 19V5M4 19h16M7 15l4-6 3 3 5-8",
  cakto: "M4 7h16v11H4zM4 10h16M8 15h4",
  ads: "M4 10v4h3l6 4V6L7 10H4zM17 8a6 6 0 0 1 0 8",
  crm: "M4 6h16v12H4zM8 6V4h8v2M8 12h8M8 15h5",
  dev: "M8 8 4 12l4 4M16 8l4 4-4 4M14 5l-4 14",
  game: "M7 8h10a5 5 0 0 1 4.5 7.2l-1.3 2.7A2 2 0 0 1 18 19l-2-2H8l-2 2a2 2 0 0 1-2.2-1.1L2.5 15.2A5 5 0 0 1 7 8zM8 12v4M6 14h4M16 12h.01M18 14h.01",
  projects: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z",
  memory: "M9 4h6v3h3v6h-3v3H9v-3H6V7h3V4zM9 10h6v4H9z",
  devices: "M4 5h11v10H4zM7 19h6M16 9h4v11h-4z",
  security: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3zM9 12l2 2 4-5",
  logs: "M4 5h16M4 10h16M4 15h10M4 20h7",
  settings: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM19 12l2 1-2 4-2-1a7 7 0 0 1-2 1l-.4 2h-5L9 17a7 7 0 0 1-2-1l-2 1-2-4 2-1a7 7 0 0 1 0-2L3 9l2-4 2 1a7 7 0 0 1 2-1l.4-2h5L15 5a7 7 0 0 1 2 1l2-1 2 4-2 1a7 7 0 0 1 0 2z",
  mic: "M12 4a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  stop: "M6 6h12v12H6z",
  play: "M8 5l11 7-11 7V5z",
  pause: "M8 5v14M16 5v14",
  check: "M4 12l5 5L20 6",
  x: "M6 6l12 12M18 6 6 18",
  refresh: "M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5",
  external: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  send: "M3 20l18-8L3 4v6l10 2-10 2v6z",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM16 16l5 5",
  plus: "M12 5v14M5 12h14",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z",
  lock: "M6 11h12v10H6zM9 11V8a3 3 0 0 1 6 0v3",
  wallet: "M3 7h18v12H3zM3 10h18M16 14h2",
  brain: "M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a3 3 0 0 0-3-1zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1",
  terminal: "M4 5h16v14H4zM8 9l3 3-3 3M13 15h4",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z",
  spark: "M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2 2-6z",
  download: "M12 4v11M7 10l5 5 5-5M5 20h14",
  alert: "M12 4l9 16H3L12 4zM12 10v4M12 17h.01",
  minimize: "M5 12h14",
  filter: "M4 6h16M7 12h10M10 18h4",
};

export function Icon({ name, size = 18, className = "" }: { name: string; size?: number; className?: string }) {
  return (
    <svg className={`icon ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name] || ICONS.spark} />
    </svg>
  );
}

export function Logo({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="JARVIS">
      <defs>
        <linearGradient id="jg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#37e6ff" />
          <stop offset="1" stopColor="#2b6bff" />
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="29" fill="#070b12" stroke="url(#jg)" strokeWidth="1.4" />
      <circle cx="32" cy="32" r="21" fill="none" stroke="url(#jg)" strokeOpacity="0.5" strokeWidth="1" strokeDasharray="4 6" />
      <path d="M32 13v38M13 32h38M19 19l26 26M45 19 19 45" stroke="url(#jg)" strokeOpacity="0.28" strokeWidth="0.9" />
      <circle cx="32" cy="32" r="10" fill="none" stroke="url(#jg)" strokeWidth="2.2" />
      <circle cx="32" cy="32" r="3.4" fill="#9ff6ff" />
      <path d="M32 8v4M32 52v4M8 32h4M52 32h4" stroke="#37e6ff" strokeWidth="1.6" />
    </svg>
  );
}

export function Card({ children, className = "", title, subtitle, actions }: {
  children?: React.ReactNode; className?: string; title?: string; subtitle?: string; actions?: React.ReactNode;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <h3>{title}</h3>}
            {subtitle && <p className="muted">{subtitle}</p>}
          </div>
          {actions && <div className="row gap-sm">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Button({ children, onClick, variant = "default", disabled, type = "button", title, icon, className = "" }: {
  children?: React.ReactNode; onClick?: () => void; variant?: "default" | "primary" | "danger" | "ghost";
  disabled?: boolean; type?: "button" | "submit"; title?: string; icon?: string; className?: string;
}) {
  return (
    <button className={`btn btn-${variant} ${className}`} onClick={onClick} disabled={disabled} type={type} title={title}>
      {icon && <Icon name={icon} size={15} />}
      {children}
    </button>
  );
}

export function Badge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: Tone }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

const STATUS_TONES: Record<string, Tone> = {
  completed: "good", passed: "good", approved: "good", online: "good", connected: "good", ok: "good",
  running: "info", planning: "info", queued: "info", validated: "good",
  awaiting_approval: "warn", paused: "warn", blocked: "warn", requires_configuration: "warn",
  demo: "warn", draft: "warn", warning: "warn", validation_pending: "warn",
  failed: "bad", error: "bad", cancelled: "bad", denied: "bad", platform_unsupported: "bad",
  partially_completed: "warn", expired: "warn",
};

export function StatusBadge({ status }: { status?: string | null }) {
  const value = status || "unknown";
  return <Badge tone={STATUS_TONES[value] || "neutral"}>{value.replaceAll("_", " ")}</Badge>;
}

export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small className="muted">{hint}</small>}
    </label>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (value: boolean) => void; label?: string }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="track"><span className="thumb" /></span>
      {label && <span>{label}</span>}
    </label>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return <div className="empty"><Icon name="spark" size={22} /><strong>{title}</strong>{hint && <span className="muted">{hint}</span>}</div>;
}

export function Spinner({ label }: { label?: string }) {
  return <div className="spinner-row"><span className="spinner" />{label && <span className="muted">{label}</span>}</div>;
}

export function Metric({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: string; tone?: Tone }) {
  return (
    <div className={`metric ${tone ? `metric-${tone}` : ""}`}>
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
      {hint && <small className="muted">{hint}</small>}
    </div>
  );
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div className={`modal ${wide ? "modal-wide" : ""}`} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <header className="modal-head"><h2>{title}</h2><Button variant="ghost" icon="x" onClick={onClose} title="Fechar" /></header>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

type Toast = { id: number; message: string; tone: Tone };
const ToastContext = createContext<{ notify: (message: string, tone?: Tone) => void }>({ notify: () => undefined });

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const notify = (message: string, tone: Tone = "info") => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, message, tone }]);
    window.setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), 6500);
  };
  const value = useMemo(() => ({ notify }), []);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast-${toast.tone}`}>
            <Icon name={toast.tone === "bad" ? "alert" : toast.tone === "good" ? "check" : "spark"} size={16} />
            <span>{toast.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

export function Orb({ active = false, listening = false, size = 320 }: { active?: boolean; listening?: boolean; size?: number }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);
    let frame = 0;
    let raf = 0;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const draw = () => {
      frame += 1;
      const t = reduce ? 0 : frame / 60;
      ctx.clearRect(0, 0, size, size);
      const cx = size / 2;
      const cy = size / 2;
      const base = size / 2 - 14;
      const pulse = active || listening ? 1 + Math.sin(t * 4) * 0.03 : 1 + Math.sin(t * 1.4) * 0.012;
      const gradient = ctx.createRadialGradient(cx, cy, 4, cx, cy, base * 1.1);
      gradient.addColorStop(0, listening ? "rgba(55,230,255,0.28)" : "rgba(43,107,255,0.22)");
      gradient.addColorStop(0.55, "rgba(10,20,40,0.08)");
      gradient.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(cx, cy, base * 1.05, 0, Math.PI * 2);
      ctx.fill();

      for (let ring = 0; ring < 4; ring += 1) {
        const radius = (base - ring * 18) * pulse;
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.strokeStyle = ring === 0 ? "rgba(55,230,255,0.7)" : `rgba(55,230,255,${0.22 - ring * 0.04})`;
        ctx.lineWidth = ring === 0 ? 1.6 : 1;
        ctx.setLineDash(ring === 2 ? [3, 10] : []);
        ctx.stroke();
      }
      ctx.setLineDash([]);
      for (let i = 0; i < 60; i += 1) {
        const angle = (i / 60) * Math.PI * 2 + (active ? t * 0.4 : t * 0.08);
        const inner = base - 34;
        const outer = base - (i % 6 === 0 ? 22 : 28);
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(angle) * inner, cy + Math.sin(angle) * inner);
        ctx.lineTo(cx + Math.cos(angle) * outer, cy + Math.sin(angle) * outer);
        ctx.strokeStyle = i % 6 === 0 ? "rgba(55,230,255,0.65)" : "rgba(80,140,255,0.25)";
        ctx.lineWidth = i % 6 === 0 ? 1.4 : 0.8;
        ctx.stroke();
      }
      const core = base * 0.33;
      ctx.beginPath();
      ctx.arc(cx, cy, core, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(5,10,18,0.85)";
      ctx.fill();
      ctx.strokeStyle = listening ? "rgba(160,250,255,0.95)" : "rgba(55,230,255,0.55)";
      ctx.lineWidth = 1.3;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(cx, cy, core * (listening ? 0.45 + Math.abs(Math.sin(t * 3)) * 0.16 : 0.38), 0, Math.PI * 2);
      const coreGradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, core);
      coreGradient.addColorStop(0, "rgba(200,255,255,0.95)");
      coreGradient.addColorStop(1, "rgba(43,107,255,0.05)");
      ctx.fillStyle = coreGradient;
      ctx.fill();
      if (!reduce) raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [active, listening, size]);
  return <canvas ref={canvasRef} style={{ width: size, height: size }} className="orb" aria-hidden="true" />;
}

export function CodeBlock({ value }: { value: string }) {
  return (
    <pre className="codeblock">
      <code>{value}</code>
    </pre>
  );
}

export function CopyButton({ value, label = "Copiar" }: { value: string; label?: string }) {
  const { notify } = useToast();
  return (
    <Button variant="ghost" icon="projects" onClick={async () => {
      try {
        await navigator.clipboard.writeText(value);
        notify("Copiado para a area de transferencia.", "good");
      } catch {
        notify("Nao foi possivel copiar automaticamente.", "bad");
      }
    }}>{label}</Button>
  );
}
