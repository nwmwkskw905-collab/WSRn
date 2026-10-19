"""Guards against the UI inventing endpoints, icons or navigation targets.

The renderer is plain TypeScript/React, so these checks parse the source instead of
running a browser. They fail the suite when a screen calls a route that the runtime
does not expose, which is exactly the class of bug that "demo dashboards" hide.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "apps" / "desktop" / "src" / "renderer"
API_FILE = RENDERER / "lib" / "api.ts"
UI_FILE = RENDERER / "components" / "ui.tsx"
APP_FILE = RENDERER / "App.tsx"

ENDPOINT_RE = re.compile(r"[\"'`](/api/[^\"'`]*)[\"'`]")
ICON_USE_RE = re.compile(r"[Ii]con(?:=|name=)[\"']([a-z0-9-]+)[\"']")
ICON_DEF_RE = re.compile(r"^\s{2}([a-z0-9]+): \"", re.MULTILINE)


def _normalize(path: str) -> str:
    path = path.split("?")[0].strip().rstrip("/")
    path = re.sub(r"\{[^}]*\}", "{}", path)
    return path or "/"


def _extract_endpoints(text: str) -> list[str]:
    """Collect literal /api/ paths, collapsing ${...} interpolations safely.

    Template literals may contain nested braces and quotes inside the interpolation
    (e.g. `${id.replace("…", "")}`), so a regex over the raw text is not enough.
    """
    found: list[str] = []
    index = 0
    while True:
        start = text.find("/api/", index)
        if start == -1:
            break
        out: list[str] = []
        i = start
        while i < len(text):
            ch = text[i]
            if ch == "$" and i + 1 < len(text) and text[i + 1] == "{":
                depth = 1
                i += 2
                while i < len(text) and depth:
                    if text[i] == "{":
                        depth += 1
                    elif text[i] == "}":
                        depth -= 1
                    i += 1
                if out and out[-1] == "/":
                    out.append("{}")
                continue
            if ch in "`'\" \n\t)?&;:,<>*":
                break
            out.append(ch)
            i += 1
        found.append("".join(out))
        index = i + 1
    return found


def _segments_match(candidate: str, known: str) -> bool:
    """A placeholder in the UI may resolve to any literal, but static parts must match."""
    left = candidate.strip("/").split("/")
    right = known.strip("/").split("/")
    if len(left) != len(right):
        return False
    return all(a == b or a == "{}" or b == "{}" for a, b in zip(left, right))


def _renderer_sources() -> list[Path]:
    return sorted(RENDERER.rglob("*.tsx")) + sorted(RENDERER.rglob("*.ts"))


@pytest.fixture(scope="module")
def openapi_paths():
    from jarvis.main import app

    return app.openapi()["paths"]


def test_every_renderer_endpoint_exists(openapi_paths):
    known_paths = [_normalize(path) for path in openapi_paths]
    missing: list[str] = []
    checked = 0
    for source in _renderer_sources():
        for raw in _extract_endpoints(source.read_text(encoding="utf-8")):
            endpoint = _normalize(raw)
            checked += 1
            if not any(_segments_match(endpoint, known) for known in known_paths):
                missing.append(f"{source.relative_to(ROOT)} -> {raw}")
    assert checked >= 40, f"Poucos endpoints detectados ({checked}); o parser provavelmente quebrou"
    assert not missing, "Endpoints chamados pela interface que nao existem no runtime:\n" + "\n".join(sorted(set(missing)))


def test_settings_keys_written_by_ui_are_known():
    """PUT /api/settings/{key} accepts any key, so we assert the UI uses documented ones."""
    allowed = {"voice", "mobile.public_url", "windows.allowed_apps"}
    used = set()
    for source in _renderer_sources():
        text = source.read_text(encoding="utf-8")
        for match in re.finditer(r"/api/settings/([a-zA-Z0-9_.]+)", text):
            used.add(match.group(1))
    assert used <= allowed, f"Chaves de configuracao nao documentadas: {used - allowed}"


def test_navigation_has_twenty_sections_and_all_pages():
    app_source = APP_FILE.read_text(encoding="utf-8")
    nav_block = app_source.split("const NAV = [", 1)[1].split("];", 1)[0]
    sections = re.findall(r"label: \"([^\"]+)\", icon:", nav_block)
    assert len(sections) == 20, f"Esperadas 20 secoes, encontradas {len(sections)}: {sections}"
    ids = set(re.findall(r"id: \"([a-z]+)\"", nav_block))

    page_ids = set(re.findall(r"\b([a-z]+): <\w+Page\b", app_source))
    assert ids == page_ids, f"Secoes sem componente: {ids - page_ids}; componentes sem secao: {page_ids - ids}"


def test_icons_referenced_by_pages_are_defined():
    defined = set(ICON_DEF_RE.findall(UI_FILE.read_text(encoding="utf-8")))
    assert len(defined) >= 20, "Tabela de icones inesperadamente pequena"
    missing: set[str] = set()
    for source in _renderer_sources():
        for name in ICON_USE_RE.findall(source.read_text(encoding="utf-8")):
            if name not in defined:
                missing.add(f"{source.name}:{name}")
    assert not missing, f"Icones inexistentes: {sorted(missing)}"


def test_no_placeholder_handlers_in_pages():
    """Buttons must call the API or navigate; alert('em breve') style stubs are rejected."""
    banned = ("em breve", r"\bTODO\b", "lorem ipsum", "not implemented", "mock data", "fake data")
    offenders = []
    for source in sorted(RENDERER.rglob("pages/*.tsx")):
        text = source.read_text(encoding="utf-8")
        for token in banned:
            if re.search(token, text, re.IGNORECASE):
                offenders.append(f"{source.name}: {token}")
    assert not offenders, f"Conteudo provisorio encontrado: {offenders}"
