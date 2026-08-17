#!/usr/bin/env python3
"""Collect the day's offers from every reachable store and render the page.

Usage: python3 run.py [--only falabella,tailoy] [--out ofertas.html]

Writes the rendered page plus a data.json snapshot next to it, and prints a
one-line summary that the scheduled job forwards as the notification.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import falabella
import render
import tailoy

STORES = {"falabella": falabella, "tailoy": tailoy}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated store keys")
    ap.add_argument("--out", default="ofertas.html")
    args = ap.parse_args()

    keys = [k.strip() for k in args.only.split(",") if k.strip()] or list(STORES)
    items, failed = [], []
    for k in keys:
        mod = STORES.get(k)
        if not mod:
            print(f"tienda desconocida: {k}", file=sys.stderr)
            continue
        print(f"[{k}]", file=sys.stderr)
        try:
            got = mod.scrape(log=lambda m: print(m, file=sys.stderr))
        except Exception as exc:  # a store going down must not sink the run
            print(f"  ERROR {k}: {exc}", file=sys.stderr)
            failed.append(k)
            continue
        if not got:
            failed.append(k)
        items += got

    if not items:
        print("ERROR: ninguna tienda devolvio datos", file=sys.stderr)
        return 1

    info = render.build(items, args.out)
    data_path = os.path.join(os.path.dirname(args.out) or ".", "data.json")
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)

    info["failed"] = failed
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
