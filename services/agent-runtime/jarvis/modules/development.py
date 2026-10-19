"""Development Studio: generates real projects, runs real tests, records artifacts.

Templates are intentionally small but complete. The studio never claims a build
succeeded unless the generated test command exits 0; when a toolchain is missing it
reports exactly what is missing.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..config import CONFIG
from ..db import get_db, new_id, now_iso


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or f"project-{int(time.time())}"


FASTAPI_APP = '''"""Produto de exemplo gerado pelo JARVIS Development Studio."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DB_PATH = Path(os.environ.get("APP_DB", Path(__file__).parent / "products.sqlite3"))
app = FastAPI(title="Cadastro de Produtos")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS products (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT NOT NULL,
                   price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
                   stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
                   created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
               )"""
        )


class ProductIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    price_cents: int = Field(ge=0)
    stock: int = Field(default=0, ge=0)


init_db()


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/products")
def list_products() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/products", status_code=201)
def create_product(payload: ProductIn) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO products(name, price_cents, stock) VALUES (?,?,?)",
            (payload.name, payload.price_cents, payload.stock),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM products WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.put("/api/products/{product_id}")
def update_product(product_id: int, payload: ProductIn) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE products SET name=?, price_cents=?, stock=? WHERE id=?",
            (payload.name, payload.price_cents, payload.stock, product_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Produto nao encontrado")
        row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    return dict(row)


@app.delete("/api/products/{product_id}", status_code=204)
def delete_product(product_id: int) -> None:
    with connect() as conn:
        cur = conn.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Produto nao encontrado")


static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")
'''

FASTAPI_TESTS = '''import os
import tempfile
from pathlib import Path

os.environ["APP_DB"] = str(Path(tempfile.mkdtemp()) / "test.sqlite3")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_create_and_list_product():
    response = client.post("/api/products", json={"name": "Caneta", "price_cents": 250, "stock": 10})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Caneta"
    listing = client.get("/api/products").json()
    assert any(p["id"] == body["id"] for p in listing)


def test_rejects_negative_price():
    response = client.post("/api/products", json={"name": "Invalido", "price_cents": -1})
    assert response.status_code == 422


def test_update_and_delete():
    created = client.post("/api/products", json={"name": "Lapis", "price_cents": 100}).json()
    updated = client.put(f"/api/products/{created['id']}", json={"name": "Lapis HB", "price_cents": 150, "stock": 3})
    assert updated.json()["name"] == "Lapis HB"
    assert client.delete(f"/api/products/{created['id']}").status_code == 204
    assert client.delete(f"/api/products/{created['id']}").status_code == 404
'''

FASTAPI_INDEX = '''<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Cadastro de Produtos</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <main>
    <h1>Cadastro de Produtos</h1>
    <form id="form">
      <input id="name" placeholder="Nome" required minlength="2" />
      <input id="price" type="number" min="0" step="0.01" placeholder="Preco (R$)" required />
      <input id="stock" type="number" min="0" step="1" placeholder="Estoque" value="0" />
      <button type="submit">Cadastrar</button>
    </form>
    <p id="status" role="status"></p>
    <table>
      <thead><tr><th>ID</th><th>Nome</th><th>Preco</th><th>Estoque</th><th></th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
'''

FASTAPI_CSS = '''body { font-family: system-ui, sans-serif; background:#0d1117; color:#e6edf3; margin:0; }
main { max-width: 760px; margin: 48px auto; padding: 0 16px; }
form { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px; }
input, button { padding:10px; border-radius:8px; border:1px solid #30363d; background:#161b22; color:#e6edf3; }
button { background:#1f6feb; cursor:pointer; }
table { width:100%; border-collapse:collapse; } td, th { padding:8px; border-bottom:1px solid #30363d; text-align:left; }
#status { color:#7ee787; }
'''

FASTAPI_JS = '''const form = document.getElementById('form');
const rows = document.getElementById('rows');
const status = document.getElementById('status');

async function load() {
  const data = await fetch('/api/products').then(r => r.json());
  rows.innerHTML = '';
  for (const p of data) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${p.id}</td><td>${p.name}</td><td>R$ ${(p.price_cents/100).toFixed(2)}</td><td>${p.stock}</td>`;
    const td = document.createElement('td');
    const btn = document.createElement('button');
    btn.textContent = 'Excluir';
    btn.onclick = async () => { await fetch(`/api/products/${p.id}`, {method:'DELETE'}); load(); };
    td.appendChild(btn); tr.appendChild(td); rows.appendChild(tr);
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = {
    name: document.getElementById('name').value.trim(),
    price_cents: Math.round(Number(document.getElementById('price').value) * 100),
    stock: Number(document.getElementById('stock').value || 0),
  };
  const res = await fetch('/api/products', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  status.textContent = res.ok ? 'Produto cadastrado.' : 'Erro ao cadastrar.';
  form.reset(); load();
});

load();
'''

FASTAPI_REQ = '''fastapi>=0.115,<1
uvicorn>=0.30,<1
pydantic>=2.7,<3
pytest>=8,<9
httpx>=0.27,<1
'''

INVENTORY_LOGIC = '''"""Nucleo de estoque, vendas e caixa (sem interface), testavel."""
from __future__ import annotations

import sqlite3
from pathlib import Path


class Store:
    def __init__(self, db_path: str | Path = "store.sqlite3"):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT NOT NULL, price_cents INTEGER NOT NULL, stock INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, qty INTEGER NOT NULL, total_cents INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS cash(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, amount_cents INTEGER NOT NULL, note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            """
        )
        self.conn.commit()

    def add_product(self, name: str, price_cents: int, stock: int) -> int:
        if price_cents < 0 or stock < 0:
            raise ValueError("Valores negativos nao permitidos")
        cur = self.conn.execute("INSERT INTO products(name, price_cents, stock) VALUES (?,?,?)", (name, price_cents, stock))
        self.conn.commit()
        return int(cur.lastrowid)

    def sell(self, product_id: int, qty: int) -> dict:
        if qty <= 0:
            raise ValueError("Quantidade invalida")
        row = self.conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not row:
            raise KeyError("Produto inexistente")
        if row["stock"] < qty:
            raise ValueError("Estoque insuficiente")
        total = row["price_cents"] * qty
        self.conn.execute("UPDATE products SET stock=stock-? WHERE id=?", (qty, product_id))
        cur = self.conn.execute("INSERT INTO sales(product_id, qty, total_cents) VALUES (?,?,?)", (product_id, qty, total))
        self.conn.execute("INSERT INTO cash(kind, amount_cents, note) VALUES ('sale', ?, ?)", (total, f"Venda #{cur.lastrowid}"))
        self.conn.commit()
        return {"sale_id": cur.lastrowid, "total_cents": total, "remaining_stock": row["stock"] - qty}

    def cash_balance_cents(self) -> int:
        row = self.conn.execute("SELECT COALESCE(SUM(CASE WHEN kind='sale' THEN amount_cents ELSE -amount_cents END),0) v FROM cash").fetchone()
        return int(row["v"])

    def report(self) -> dict:
        sales = self.conn.execute("SELECT COUNT(*) n, COALESCE(SUM(total_cents),0) total FROM sales").fetchone()
        low = self.conn.execute("SELECT name, stock FROM products WHERE stock <= 5 ORDER BY stock").fetchall()
        return {"sales_count": sales["n"], "sales_total_cents": sales["total"], "cash_cents": self.cash_balance_cents(), "low_stock": [dict(r) for r in low]}
'''

INVENTORY_UI = '''"""Interface Tkinter opcional. Requer ambiente grafico do Windows."""
import tkinter as tk
from tkinter import messagebox, ttk

from logic import Store


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("JARVIS Estoque, Vendas e Caixa")
        self.geometry("760x480")
        self.store = Store()
        self._build()

    def _build(self):
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        self.name = ttk.Entry(frame)
        self.price = ttk.Entry(frame)
        self.stock = ttk.Entry(frame)
        for i, (label, widget) in enumerate([("Nome", self.name), ("Preco (centavos)", self.price), ("Estoque", self.stock)]):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", pady=4)
            widget.grid(row=i, column=1, sticky="ew", pady=4)
        ttk.Button(frame, text="Cadastrar produto", command=self.add).grid(row=3, column=0, columnspan=2, pady=8)
        self.output = tk.Text(frame, height=18)
        self.output.grid(row=4, column=0, columnspan=2, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(4, weight=1)
        self.refresh()

    def add(self):
        try:
            self.store.add_product(self.name.get().strip(), int(self.price.get()), int(self.stock.get()))
        except ValueError as exc:
            messagebox.showerror("Erro", str(exc))
            return
        self.refresh()

    def refresh(self):
        report = self.store.report()
        self.output.delete("1.0", "end")
        self.output.insert("end", f"Vendas: {report['sales_count']}\\nTotal vendido: R$ {report['sales_total_cents']/100:.2f}\\nCaixa: R$ {report['cash_cents']/100:.2f}\\n")
        for item in report["low_stock"]:
            self.output.insert("end", f"Estoque baixo: {item['name']} ({item['stock']})\\n")


if __name__ == "__main__":
    App().mainloop()
'''

INVENTORY_TEST = '''import tempfile
from pathlib import Path

from app.logic import Store


def make_store():
    return Store(Path(tempfile.mkdtemp()) / "store.sqlite3")


def test_sale_updates_stock_and_cash():
    store = make_store()
    product_id = store.add_product("Cafe", 1500, 10)
    result = store.sell(product_id, 2)
    assert result["total_cents"] == 3000
    assert store.cash_balance_cents() == 3000
    assert store.report()["sales_count"] == 1


def test_insufficient_stock_rejected():
    store = make_store()
    product_id = store.add_product("Cafe", 1500, 1)
    try:
        store.sell(product_id, 5)
    except ValueError as exc:
        assert "insuficiente" in str(exc)
    else:
        raise AssertionError("venda deveria falhar")


def test_low_stock_report():
    store = make_store()
    store.add_product("Raro", 100, 2)
    assert len(store.report()["low_stock"]) == 1
'''

GODOT_PROJECT = '''; JARVIS Game Studio - prototipo de corrida 2D/3D simples
config_version=5

[application]
config/name="JARVIS Moto Racer"
run/main_scene="res://scenes/Main.tscn"
config/features=PackedStringArray("4.3", "Forward Plus")

[display]
window/size/viewport_width=1280
window/size/viewport_height=720

[input]
accelerate={
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":0,"physical_keycode":87,"key_label":0,"unicode":0,"location":0,"echo":false,"script":null)]
}
brake={
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":0,"physical_keycode":83,"key_label":0,"unicode":0,"location":0,"echo":false,"script":null)]
}
steer_left={
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":0,"physical_keycode":65,"key_label":0,"unicode":0,"location":0,"echo":false,"script":null)]
}
steer_right={
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":0,"physical_keycode":68,"key_label":0,"unicode":0,"location":0,"echo":false,"script":null)]
}
restart={
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":0,"physical_keycode":82,"key_label":0,"unicode":0,"location":0,"echo":false,"script":null)]
}

[rendering]
renderer/rendering_method="forward_plus"
'''

GODOT_MAIN_SCENE = '''[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/main.gd" id="1"]

[node name="Main" type="Node3D"]
script = ExtResource("1")
'''

GODOT_MAIN = '''extends Node3D

var speed := 0.0
var steering := 0.0
var elapsed := 0.0
var running := true
var checkpoints_hit := 0
var total_checkpoints := 4
var bike: CharacterBody3D
var camera: Camera3D
var hud: Label
var track_radius := 42.0

func _ready() -> void:
    _build_environment()
    _build_track()
    _build_bike()
    _build_hud()
    Input.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)

func _build_environment() -> void:
    var world := WorldEnvironment.new()
    var env := Environment.new()
    env.background_mode = Environment.BG_SKY
    var sky := Sky.new()
    sky.sky_material = ProceduralSkyMaterial.new()
    env.sky = sky
    env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
    world.environment = env
    add_child(world)
    var light := DirectionalLight3D.new()
    light.rotation_degrees = Vector3(-55, -30, 0)
    light.light_energy = 1.2
    add_child(light)

func _build_track() -> void:
    var ground := StaticBody3D.new()
    var mesh := MeshInstance3D.new()
    var plane := PlaneMesh.new()
    plane.size = Vector2(400, 400)
    mesh.mesh = plane
    var mat := StandardMaterial3D.new()
    mat.albedo_color = Color(0.08, 0.1, 0.14)
    mesh.material_override = mat
    ground.add_child(mesh)
    var shape := CollisionShape3D.new()
    var box := BoxShape3D.new()
    box.size = Vector3(400, 1, 400)
    shape.shape = box
    shape.position.y = -0.5
    ground.add_child(shape)
    add_child(ground)
    for i in range(36):
        var angle := TAU * i / 36.0
        var marker := MeshInstance3D.new()
        var cyl := CylinderMesh.new()
        cyl.top_radius = 0.35
        cyl.bottom_radius = 0.35
        cyl.height = 1.2
        marker.mesh = cyl
        marker.position = Vector3(cos(angle) * track_radius, 0.6, sin(angle) * track_radius)
        add_child(marker)
    for i in range(total_checkpoints):
        var angle := TAU * i / total_checkpoints
        var cp := Area3D.new()
        cp.name = "Checkpoint%d" % i
        var shape := CollisionShape3D.new()
        var box := BoxShape3D.new()
        box.size = Vector3(10, 4, 2)
        shape.shape = box
        cp.add_child(shape)
        cp.position = Vector3(cos(angle) * track_radius, 2, sin(angle) * track_radius)
        cp.rotation.y = -angle
        cp.body_entered.connect(_on_checkpoint.bind(i))
        add_child(cp)

func _build_bike() -> void:
    bike = CharacterBody3D.new()
    var body := MeshInstance3D.new()
    var capsule := CapsuleMesh.new()
    capsule.radius = 0.5
    capsule.height = 2.0
    body.mesh = capsule
    body.rotation_degrees = Vector3(0, 0, 90)
    var mat := StandardMaterial3D.new()
    mat.albedo_color = Color(0.1, 0.8, 1.0)
    body.material_override = mat
    bike.add_child(body)
    var shape := CollisionShape3D.new()
    var capsule_shape := CapsuleShape3D.new()
    capsule_shape.radius = 0.5
    capsule_shape.height = 2.0
    shape.shape = capsule_shape
    bike.add_child(shape)
    bike.position = Vector3(track_radius, 1, 0)
    add_child(bike)
    camera = Camera3D.new()
    camera.position = Vector3(0, 4, 8)
    bike.add_child(camera)

func _build_hud() -> void:
    var layer := CanvasLayer.new()
    hud = Label.new()
    hud.position = Vector2(24, 20)
    hud.add_theme_font_size_override("font_size", 22)
    layer.add_child(hud)
    add_child(layer)

func _physics_process(delta: float) -> void:
    if not running:
        if Input.is_action_just_pressed("restart"):
            get_tree().reload_current_scene()
        return
    elapsed += delta
    var throttle := Input.get_action_strength("accelerate") - Input.get_action_strength("brake")
    speed = clamp(speed + throttle * 18.0 * delta, 0.0, 45.0)
    speed = max(speed - 4.0 * delta, 0.0)
    steering = Input.get_action_strength("steer_left") - Input.get_action_strength("steer_right")
    bike.rotate_y(steering * delta * 1.6 * clamp(speed / 20.0, 0.15, 1.0))
    var forward := -bike.global_transform.basis.z
    bike.velocity = forward * speed
    bike.velocity.y = -9.8
    bike.move_and_slide()
    var cam := bike.get_node_or_null("Camera3D")
    if cam:
        cam.look_at(bike.global_position + forward * 6.0, Vector3.UP)
    hud.text = "Tempo: %.1fs   Velocidade: %.0f km/h   Checkpoints: %d/%d" % [elapsed, speed * 3.6, checkpoints_hit, total_checkpoints]
    if checkpoints_hit >= total_checkpoints:
        running = false
        hud.text = "Volta concluida em %.1fs! Pressione R para reiniciar." % elapsed

func _on_checkpoint(body: Node3D, index: int) -> void:
    if body != bike:
        return
    if index == checkpoints_hit:
        checkpoints_hit += 1
'''

README_TEMPLATE = """# {name}

Gerado pelo JARVIS Development Studio.

Objetivo: {objective}

## Execucao

{run}

## Testes

{tests}

## Limitacoes

Gerado automaticamente como ponto de partida funcional. Revise o codigo antes de
usar em producao. Nenhum build foi alegado sem execucao real.
"""


class DevelopmentStudio:
    def __init__(self) -> None:
        self.db = get_db()
        CONFIG.ensure_dirs()

    def create(self, kind: str, name: str, objective: str, run_tests: bool = True) -> dict[str, Any]:
        slug = slugify(name)
        root = CONFIG.workspace_dir / "projects" / slug
        if root.exists():
            slug = f"{slug}-{int(time.time())}"
            root = CONFIG.workspace_dir / "projects" / slug
        root.mkdir(parents=True, exist_ok=False)
        if kind == "web-app":
            files = self._web_app_files()
            tests_cmd = f"{sys.executable} -m pytest -q"
        elif kind == "inventory-system":
            files = self._inventory_files()
            tests_cmd = f"{sys.executable} -m pytest -q"
        elif kind == "godot-2d-racer":
            files = self._godot_files()
            tests_cmd = ""
        else:
            raise ValueError(f"Tipo de projeto nao suportado: {kind}")
        written = []
        for rel, content in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written.append({"path": str(target.relative_to(root)), "bytes": target.stat().st_size,
                            "sha256": hashlib.sha256(content.encode()).hexdigest()})
        readme = README_TEMPLATE.format(
            name=name,
            objective=objective,
            run=("`uvicorn app.main:app --reload`" if kind == "web-app" else
                 "`python app/ui.py` (Windows com Tkinter)" if kind == "inventory-system" else
                 "Abra a pasta no Godot 4.3+ e pressione F5"),
            tests=(f"`{tests_cmd}`" if tests_cmd else "Sem testes automatizados; validacao exige Godot instalado."),
        )
        (root / "README.md").write_text(readme, encoding="utf-8")
        written.append({"path": "README.md", "bytes": len(readme), "sha256": hashlib.sha256(readme.encode()).hexdigest()})
        syntax = self._syntax_check(root)
        test_result = None
        if run_tests and tests_cmd:
            test_result = self._run_tests(root, tests_cmd)
        project_id = new_id("proj_")
        ts = now_iso()
        metadata = {
            "files": written,
            "syntax": syntax,
            "tests": test_result,
            "tests_command": tests_cmd,
            "build": "not_requested" if kind == "web-app" else "not_applicable",
        }
        self.db.execute(
            "INSERT INTO projects(id, name, kind, path, objective, status, metadata_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (project_id, name, kind, str(root), objective,
             "validated" if (test_result and test_result["exit_code"] == 0) else "created",
             json.dumps(metadata, default=str), ts, ts),
        )
        for item in written:
            self.db.execute(
                "INSERT INTO artifacts(id, task_id, project_id, name, path, kind, size_bytes, sha256, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (new_id("art_"), None, project_id, item["path"], str(root / item["path"]), "file",
                 item["bytes"], item["sha256"], ts),
            )
        return {
            "project_id": project_id,
            "name": name,
            "kind": kind,
            "path": str(root),
            "files": [w["path"] for w in written],
            "syntax_check": syntax,
            "tests": test_result,
            "status": "validated" if (test_result and test_result["exit_code"] == 0) else "created",
            "limitations": (
                ["Testes executados; build de instalador nao foi gerado por este modulo."]
                if kind == "web-app" else
                ["Interface Tkinter exige Windows com display; testes cobrem apenas o nucleo."]
                if kind == "inventory-system" else
                ["Godot nao esta instalado neste ambiente; projeto nao foi aberto/exportado.",
                 "Modelos 3D sao primitivas geradas em tempo de execucao; nao ha assets externos."]
            ),
        }

    def _web_app_files(self) -> dict[str, str]:
        return {
            "app/__init__.py": "",
            "app/main.py": FASTAPI_APP,
            "app/static/index.html": FASTAPI_INDEX,
            "app/static/style.css": FASTAPI_CSS,
            "app/static/app.js": FASTAPI_JS,
            "tests/test_products.py": FASTAPI_TESTS,
            "requirements.txt": FASTAPI_REQ,
            "pytest.ini": "[pytest]\ntestpaths = tests\n",
        }

    def _inventory_files(self) -> dict[str, str]:
        return {
            "app/__init__.py": "",
            "app/logic.py": INVENTORY_LOGIC,
            "app/ui.py": INVENTORY_UI,
            "tests/test_logic.py": INVENTORY_TEST,
            "requirements.txt": "pytest>=8,<9\n",
            "pytest.ini": "[pytest]\ntestpaths = tests\n",
        }

    def _godot_files(self) -> dict[str, str]:
        return {
            "project.godot": GODOT_PROJECT,
            "scenes/Main.tscn": GODOT_MAIN_SCENE,
            "scripts/main.gd": GODOT_MAIN,
        }

    def _syntax_check(self, root: Path) -> dict[str, Any]:
        py_files = list(root.rglob("*.py"))
        if not py_files:
            return {"status": "not_applicable", "files": 0}
        proc = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", str(root)],
            capture_output=True, text=True, timeout=60,
        )
        return {
            "status": "passed" if proc.returncode == 0 else "failed",
            "files": len(py_files),
            "stderr": proc.stderr[-2000:],
        }

    def _run_tests(self, root: Path, command: str) -> dict[str, Any]:
        env = dict(os.environ)
        env["PYTHONPATH"] = f"{root}:{env.get('PYTHONPATH', '')}"
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q"],
                cwd=str(root), capture_output=True, text=True, timeout=180, env=env,
            )
        except subprocess.TimeoutExpired:
            return {"exit_code": None, "stdout": "", "stderr": "timeout de 180s", "command": command, "status": "timeout"}
        return {
            "command": command,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-6000:],
            "stderr": proc.stderr[-3000:],
            "status": "passed" if proc.returncode == 0 else "failed",
        }

    def list_projects(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM projects ORDER BY created_at DESC")
        for row in rows:
            try:
                row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                row["metadata"] = {}
        return rows


_service: DevelopmentStudio | None = None


def get_development() -> DevelopmentStudio:
    global _service
    if _service is None:
        _service = DevelopmentStudio()
    return _service
