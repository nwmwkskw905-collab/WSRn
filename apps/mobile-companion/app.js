const store = {
  get url() { return localStorage.getItem("jarvis.url") || ""; },
  set url(value) { localStorage.setItem("jarvis.url", value.replace(/\/$/, "")); },
  get token() { return localStorage.getItem("jarvis.token") || ""; },
  set token(value) { localStorage.setItem("jarvis.token", value); },
  get device() { return localStorage.getItem("jarvis.device") || "iPhone"; },
  set device(value) { localStorage.setItem("jarvis.device", value); },
};

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; };

function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.add("hidden"), 4200);
}

async function request(method, path, body) {
  if (!store.url || !store.token) throw new Error("Pareie o dispositivo primeiro.");
  const response = await fetch(`${store.url}${path}`, {
    method,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${store.token}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!response.ok) {
    if (response.status === 401) { setOffline("token invalido"); throw new Error("Token expirado. Pareie novamente no PC."); }
    throw new Error(data?.detail || `HTTP ${response.status}`);
  }
  return data;
}

function setOffline(message) {
  const pill = $("conn");
  pill.textContent = message || "offline";
  pill.className = "pill offline";
}
function setOnline() {
  const pill = $("conn");
  pill.textContent = "pareado";
  pill.className = "pill online";
}

async function checkHealth() {
  if (!store.url || !store.token) return setOffline();
  try {
    await request("GET", "/api/status");
    setOnline();
  } catch (error) {
    setOffline(String(error.message || error).slice(0, 24));
  }
}

function showApp() {
  $("setup").classList.add("hidden");
  $("app").classList.remove("hidden");
  setOnline();
  void loadTasks();
  void loadSales();
  void loadApprovals();
  void loadChat();
}

async function pair() {
  const url = $("url").value.trim();
  const code = $("code").value.trim();
  const device = $("device").value.trim() || "iPhone";
  const msg = $("setupMsg");
  if (!/^https:\/\//.test(url)) { msg.textContent = "Use uma URL HTTPS publica (obrigatorio para a PWA no iPhone)."; return; }
  if (!/^\d{6}$/.test(code)) { msg.textContent = "O codigo tem 6 digitos."; return; }
  msg.textContent = "Pareando...";
  try {
    const response = await fetch(`${url.replace(/\/$/, "")}/api/mobile/claim`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, device_name: device }),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.detail || `HTTP ${response.status}`);
    store.url = url;
    store.token = data.token;
    store.device = device;
    msg.textContent = "";
    showApp();
    toast("Dispositivo pareado.");
  } catch (error) {
    msg.textContent = `Falha: ${error.message}`;
  }
}

async function loadChat() {
  try {
    const data = await request("GET", "/api/messages?conversation_id=main&limit=30");
    const log = $("log");
    log.textContent = "";
    for (const message of data.messages || []) {
      log.append(el("div", `bubble ${message.role === "user" ? "user" : ""}`, message.content));
    }
    log.scrollTop = log.scrollHeight;
  } catch (error) { toast(error.message); }
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("message");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  const log = $("log");
  log.append(el("div", "bubble user", text));
  try {
    const data = await request("POST", "/api/mobile/chat", { message: text, conversation_id: "main" });
    log.append(el("div", "bubble", data.reply || "(sem resposta)"));
    log.scrollTop = log.scrollHeight;
  } catch (error) { toast(error.message); }
}

const STATUS_TONE = { completed: "good", running: "", queued: "", planned: "", awaiting_approval: "warn", failed: "bad", cancelled: "bad", paused: "warn" };

async function loadTasks() {
  try {
    const data = await request("GET", "/api/tasks?limit=30");
    const box = $("tasks");
    box.textContent = "";
    if (!data.tasks?.length) { box.append(el("div", "empty", "Nenhuma tarefa ainda.")); return; }
    for (const task of data.tasks) {
      const row = el("div", "row");
      const main = el("div");
      main.append(el("div", "", task.objective));
      main.append(el("div", "muted tiny", `${task.autonomy_level !== undefined ? `nivel ${task.autonomy_level} · ` : ""}${task.updated_at || ""}`));
      row.append(main, el("span", `status ${STATUS_TONE[task.status] ?? ""}`, task.status));
      box.append(row);
    }
  } catch (error) { toast(error.message); }
}

async function loadSales() {
  try {
    const [dashboard, cakto] = await Promise.all([
      request("GET", "/api/sales/dashboard"),
      request("GET", "/api/integrations/cakto/status").catch(() => null),
    ]);
    const week = dashboard.week || {};
    const month = dashboard.month || {};
    const box = $("sales");
    box.textContent = "";
    const money = (value) => (value === undefined || value === null
      ? "sem dado"
      : Number(value).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }));
    const items = [
      ["Receita paga (7d)", week.is_empty ? "sem pedidos" : money(week.gross_revenue_brl)],
      ["Pedidos pagos (7d)", week.paid_orders ?? 0],
      ["Receita paga (30d)", month.is_empty ? "sem pedidos" : money(month.gross_revenue_brl)],
      ["Ticket medio (30d)", month.average_ticket_brl ? money(month.average_ticket_brl) : "sem dado"],
      ["Status Cakto", cakto?.status || "desconhecido"],
    ];
    for (const [label, value] of items) {
      const metric = el("div", "metric");
      metric.append(el("span", "", label));
      metric.append(el("strong", "", String(value)));
      box.append(metric);
    }
    if (week.is_empty) {
      box.append(el("p", "muted tiny", "Sem pedidos sincronizados. Isso nao significa zero vendas: conecte e sincronize a Cakto no PC."));
    }
  } catch (error) { toast(error.message); }
}

async function loadApprovals() {
  try {
    const data = await request("GET", "/api/mobile/approvals");
    const box = $("approvals");
    box.textContent = "";
    if (!data.approvals?.length) { box.append(el("div", "empty", "Nenhuma aprovacao pendente.")); return; }
    for (const approval of data.approvals) {
      const card = el("div", "approval");
      card.append(el("strong", "", approval.action));
      card.append(el("span", "muted", `${approval.risk} · ${approval.summary}`));
      const actions = el("div", "actions");
      const pin = el("input");
      pin.type = "password";
      pin.inputMode = "numeric";
      pin.placeholder = approval.pin_required ? "PIN local (definido no PC)" : "PIN opcional";
      pin.maxLength = 12;
      actions.append(pin);
      for (const decision of ["approved", "denied"]) {
        const button = el("button", decision === "approved" ? "primary" : "danger", decision === "approved" ? "Aprovar" : "Negar");
        button.onclick = async () => {
          try {
            const result = await request("POST", `/api/approvals/${approval.id}/resolve`, {
              approve: decision === "approved",
              pin: pin.value || null,
              note: `mobile:${store.device}`,
            });
            toast(`${decision === "approved" ? "Aprovado" : "Negado"}: ${result.status}.`);
            await loadApprovals();
          } catch (error) { toast(error.message); }
        };
        actions.append(button);
      }
      card.append(actions);
      box.append(card);
    }
  } catch (error) { toast(error.message); }
}

function init() {
  $("pairBtn").onclick = pair;
  $("chatForm").onsubmit = sendMessage;
  $("refreshTasks").onclick = loadTasks;
  $("settingsBtn").onclick = () => {
    $("url").value = store.url;
    $("device").value = store.device;
    $("app").classList.add("hidden");
    $("setup").classList.remove("hidden");
  };
  for (const tab of document.querySelectorAll(".tabs button")) {
    tab.onclick = () => {
      for (const other of document.querySelectorAll(".tabs button")) other.classList.toggle("active", other === tab);
      for (const panel of document.querySelectorAll(".tab-panel")) panel.classList.toggle("hidden", panel.id !== `tab-${tab.dataset.tab}`);
      if (tab.dataset.tab === "tasks") void loadTasks();
      if (tab.dataset.tab === "sales") void loadSales();
      if (tab.dataset.tab === "approvals") void loadApprovals();
      if (tab.dataset.tab === "chat") void loadChat();
    };
  }
  if (store.url && store.token) { showApp(); } else { $("url").value = store.url; $("device").value = store.device; }
  setInterval(checkHealth, 15000);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => undefined);
}

init();
