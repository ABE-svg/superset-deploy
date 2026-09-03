#!/usr/bin/env python3
"""Revisão dos gráficos/dashboards para aderirem ao tema Astecha.

Roda de uma estação de trabalho contra a API REST do Superset. É idempotente e
por padrão só mostra o que faria (dry-run); passe --apply para gravar.

O que faz:
  1. Charts com `color_scheme` explícito diferente de `astecha` (ex.: supersetColors,
     modernSunset) passam a usar `astecha`. Charts SEM esquema fixado não são
     tocados: eles já herdam o default (EXTRA_CATEGORICAL_COLOR_SCHEMES isDefault).
  2. Charts com escala sequencial explícita não-Astecha (heatmap, etc.) passam a
     usar `astechaPurple`.
  3. Dashboards com `color_scheme` fixado passam a `astecha`; o cache
     `shared_label_colors` (rótulo -> cor gerado pelo esquema antigo) é zerado para
     as cores serem recalculadas no novo esquema.
  4. Rótulos semânticos de status de qualidade (OK_*, ATENCAO_*, ALERTA_*, CRITICO_*,
     SEM_INFORME_*) ganham cor fixa (`label_colors`) no dashboard onde aparecem,
     na rampa de risco da marca — assim "OK" nunca sai vermelho por sorteio.

Variáveis de ambiente: SUPERSET_BASE_URL, SUPERSET_USERNAME, SUPERSET_PASSWORD.
Uso:
  python3 scripts/chart_theme_review.py            # dry-run
  python3 scripts/chart_theme_review.py --apply
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("SUPERSET_BASE_URL", "http://localhost:8088").rstrip("/")
CATEGORICAL = "astecha"
SEQUENTIAL = "astechaPurple"
# Rampa de risco sóbria (astecha.css --risk-0..5) + cinza da marca para "sem informe".
SEMANTIC_LABEL_COLORS = {
    "OK_PERFEITO": "#4E7A63",
    "OK_BOM": "#7FA98F",
    "ATENCAO_MEDIO": "#B08A4A",
    "ALERTA_ALTO": "#A85D4A",
    "CRITICO_MUITO_ALTO": "#6E3530",
    "SEM_INFORME_MENSAL": "#B2B2B2",
}
SEQUENTIAL_KEYS = ("linear_color_scheme",)

_token = None


def login():
    global _token
    body = json.dumps({
        "username": os.environ["SUPERSET_USERNAME"],
        "password": os.environ["SUPERSET_PASSWORD"],
        "provider": "db", "refresh": True,
    }).encode()
    req = urllib.request.Request(f"{BASE}/api/v1/security/login", data=body,
                                 headers={"Content-Type": "application/json"})
    _token = json.load(urllib.request.urlopen(req))["access_token"]


def call(method, ep, payload=None):
    if _token is None:
        login()
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"{BASE}{ep}", data=data, method=method, headers={
        "Authorization": f"Bearer {_token}", "Content-Type": "application/json",
        "Referer": BASE + "/",
    })
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} {method} {ep}: {e.read()[:400]!r}")


def csrf():
    return call("GET", "/api/v1/security/csrf_token/")["result"]


def all_charts():
    out, page = [], 0
    while True:
        d = call("GET", f"/api/v1/chart/?q=(page_size:100,page:{page},columns:!(id,slice_name,viz_type,params))")
        out += d["result"]
        if len(out) >= d["count"]:
            return out
        page += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    changes = 0

    # ---- charts ----
    for c in all_charts():
        p = json.loads(c["params"] or "{}")
        new = dict(p)
        if p.get("color_scheme") and p["color_scheme"] != CATEGORICAL:
            new["color_scheme"] = CATEGORICAL
        for k in SEQUENTIAL_KEYS:
            if p.get(k) and not p[k].startswith("astecha"):
                new[k] = SEQUENTIAL
        if new != p:
            changes += 1
            diff = {k: (p.get(k), new[k]) for k in new if p.get(k) != new[k]}
            print(f"chart {c['id']:>4} {c['viz_type']:<24} {c['slice_name'][:50]:<50} {diff}")
            if args.apply:
                call("PUT", f"/api/v1/chart/{c['id']}", {"params": json.dumps(new)})

    # ---- dashboards ----
    ids = [d["id"] for d in call("GET", "/api/v1/dashboard/?q=(page_size:100,columns:!(id))")["result"]]
    for i in ids:
        d = call("GET", f"/api/v1/dashboard/{i}")["result"]
        m = json.loads(d.get("json_metadata") or "{}")
        new = json.loads(json.dumps(m))
        if m.get("color_scheme") and m["color_scheme"] != CATEGORICAL:
            new["color_scheme"] = CATEGORICAL
        shared = m.get("shared_label_colors") or {}
        labels = shared if isinstance(shared, dict) else {l: None for l in shared}
        if labels:
            new["shared_label_colors"] = {}
            semantic = {l: SEMANTIC_LABEL_COLORS[l] for l in labels if l in SEMANTIC_LABEL_COLORS}
            if semantic:
                new["label_colors"] = {**(m.get("label_colors") or {}), **semantic}
        if new != m:
            changes += 1
            diff = {k: (m.get(k), new.get(k)) for k in set(m) | set(new) if m.get(k) != new.get(k)}
            print(f"dash  {i:>4} {d['dashboard_title'][:50]:<50} {diff}")
            if args.apply:
                call("PUT", f"/api/v1/dashboard/{i}", {"json_metadata": json.dumps(new)})

    print(f"\n{changes} alteração(ões) {'aplicadas' if args.apply else 'previstas (dry-run; use --apply)'}")


if __name__ == "__main__":
    main()
