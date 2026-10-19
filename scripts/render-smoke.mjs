/**
 * Renderer smoke test without a browser.
 *
 * Loads the production bundle inside jsdom with a stubbed fetch, then clicks every
 * navigation item and fails if React throws or a page renders nothing. This catches
 * blank-screen regressions that typecheck cannot see (bad imports, undefined access
 * during first render, broken nav wiring).
 *
 * Usage: npm run smoke:render   (after `npm run build`)
 */
import { JSDOM } from "jsdom";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const dist = path.join(root, "apps/desktop/dist/renderer");
const html = fs.readFileSync(path.join(dist, "index.html"), "utf8");
const scriptSrc = html.match(/src="([^"]+\.js)"/)?.[1];
if (!scriptSrc) throw new Error("Bundle JS nao encontrado em index.html");

const dom = new JSDOM(html.replace(/<script[^>]*><\/script>/g, ""), {
  url: "http://localhost:5173/",
  pretendToBeVisual: true,
});
const { window } = dom;
global.window = window;
global.document = window.document;
Object.defineProperty(global, "navigator", { value: window.navigator, configurable: true });
Object.defineProperty(global, "localStorage", { value: window.localStorage, configurable: true });
for (const key of ["MutationObserver", "HTMLElement", "HTMLCanvasElement", "Element", "Node", "Event", "CustomEvent", "getComputedStyle", "getSelection", "SVGElement"]) {
  if (window[key] && !(key in global)) Object.defineProperty(global, key, { value: window[key], configurable: true });
}
global.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 16);
global.cancelAnimationFrame = (id) => clearTimeout(id);
global.matchMedia = window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
window.HTMLCanvasElement.prototype.getContext = () => null;
// jsdom does not implement smooth scrolling; the UI uses it to follow the chat log.
window.Element.prototype.scrollTo = function scrollTo() {};
window.setInterval = () => 0;
window.clearInterval = () => {};

const status = {
  version: "0.9.0", platform: "Win32", host: "127.0.0.1", port: 8765, mode: "production",
  kill_switch: false, pin_configured: true, permissions_granted: 3, permissions_total: 19,
  vault_backend: "dpapi", vault_available: true, tasks: {},
  capabilities: { windows_automation: true, godot: false },
};
const routes = {
  "/api/status": status,
  "/api/diagnostics": { checks: [{ name: "banco_sqlite", status: "ok" }, { name: "cofre", status: "ok" }], paths: { data_dir: "/tmp" } },
  "/api/permissions": { permissions: [{ scope: "fs.read", label: "Ler arquivos", risk: "low", granted: true, config: {} }] },
  "/api/tools": { tools: [{ name: "fs.read_text", description: "Le arquivo", scope: "fs.read", risk: "low" }] },
  "/api/skills": { skills: [] },
  "/api/tasks": { tasks: [{ id: "tsk_1", objective: "Tarefa de exemplo", status: "completed", autonomy_level: 2, mode: "test", created_at: new Date().toISOString() }] },
  "/api/approvals": { approvals: [] },
  "/api/messages": { messages: [{ id: "m1", role: "assistant", content: "Pronto para executar.", ts: new Date().toISOString(), meta: {} }] },
  "/api/agents": { agents: [{ id: "orchestrator", name: "Orquestrador", objective: "Planejar", allowed_skills: ["general.answer"], forbidden: [], verification_contract: ["evidencia"], default_autonomy: 1 }] },
  "/api/llm/state": { providers: [{ id: "openai", label: "OpenAI", kind: "cloud", models: ["gpt-4.1-mini"], requires_key: true, enabled: false, model: "gpt-4.1-mini", status: "not_configured", has_key: false }], routing_mode: "auto", budget: { month: "2026-10", calls_month: 0, tokens_month: 0, cost_usd_month: 0, calls_today: 0, cost_source: "unavailable", budget: { monthly_budget_usd: 0, max_calls_per_day: 0, allow_paid: false } } },
  "/api/sales/report": { period_days: 7, data_source: "local", orders_considered: 0, paid_orders: 0, pending_orders: 0, refunded_orders: 0, gross_revenue_brl: 0, refunds_brl: 0, fees_brl: 0, net_revenue_estimate_brl: 0, average_ticket_brl: 0, daily_revenue: {}, notes: ["Pix gerado nao e venda."], is_empty: true },
  "/api/sales/dashboard": { week: { is_empty: true }, month: { is_empty: true } },
  "/api/integrations/cakto/status": { connected: false, status: "aguardando configuracao externa", has_secret: false },
  "/api/businesses": { businesses: [] },
  "/api/leads": { leads: [], eligible_for_contact: [] },
  "/api/projects": { projects: [], artifacts: [] },
  "/api/memories": { memories: [] },
  "/api/ads/config": { meta: {}, budget_policy: { enabled: false, daily_limit_brl: 0, monthly_limit_brl: 0 } },
  "/api/ads/campaigns": { campaigns: [] },
  "/api/research/config": { provider: "none", providers: ["none", "searxng"] },
  "/api/cakto/products": { results: [], mode: "demonstracao", warning: "sem credenciais" },
  "/api/cakto/webhook-events": { events: [] },
  "/api/products": { products: [] },
  "/api/mobile/devices": { devices: [] },
  "/api/logs/audit": { audit: [] },
  "/api/logs/events": { events: [] },
  "/api/schedules": { schedules: [] },
  "/api/settings": {},
  "/api/validation/run": { summary: { passed: 0, pending: 0, failed: 0, blocked: 0, total: 0 }, scenarios: {} },
};
const fetchStub = async (input) => {
  const url = String(input);
  const key = Object.keys(routes).find((candidate) => url.includes(candidate));
  const body = key ? routes[key] : {};
  return { ok: true, status: 200, text: async () => JSON.stringify(body), json: async () => body };
};
window.fetch = fetchStub;
global.fetch = fetchStub;

const errors = [];
window.addEventListener("error", (event) => errors.push(String(event.message || event.error)));
window.addEventListener("unhandledrejection", (event) => errors.push(String(event.reason)));

await import(path.join(dist, scriptSrc) + `?t=${Date.now()}`);
await new Promise((resolve) => setTimeout(resolve, 300));

const navItems = [...document.querySelectorAll(".nav-item")];
const results = [];
for (const item of navItems) {
  item.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 40));
  const main = document.querySelector(".page-scroll");
  const text = (main?.textContent || "").trim();
  results.push({ label: item.textContent?.trim() || "?", chars: text.length });
}
const blank = results.filter((entry) => entry.chars < 20);
const report = { navItems: results.length, blank, errors: errors.slice(0, 5) };
console.log(JSON.stringify(report, null, 2));
process.exit(blank.length === 0 && errors.length === 0 && results.length === 20 ? 0 : 1);
