"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    rows = pr.get("rows") or []
    man = pr.get("manifest") or {}
    bman = base.get("manifest") or {}

    # 1. Metric values must be real numbers: NaN compares False to every threshold and slips through.
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (a crashed grader must not read as a pass)")

    # 2. Grader crashes: reported failures, or graded cells left empty (None drops out of the mean).
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s) in the report")
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    holes: dict[str, int] = {}
    for r in rows:
        for m in graded:
            v = r.get(m)
            if v is None or (isinstance(v, float) and not math.isfinite(v)) or not isinstance(v, bool):
                holes[m] = holes.get(m, 0) + 1
    problems += [f"{n} row(s) with no valid value for graded metric {m}" for m, n in sorted(holes.items())]

    # 3. Row count and (item, seed) coverage: nothing dropped, duplicated or cherry-picked.
    want_n = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want_n:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(man.get('seeds') or [])} seeds = {want_n}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = len(keys) - len(set(keys))
    if dups:
        problems.append(f"{dups} duplicated (item, seed) row(s)")
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if set(keys) != base_keys:
        miss, extra = len(base_keys - set(keys)), len(set(keys) - base_keys)
        problems.append(f"(item, seed) set differs from baseline: {miss} missing, {extra} extra")
    for field in ("items", "seeds"):
        if man.get(field) != bman.get(field):
            problems.append(f"manifest {field} {man.get(field)!r} != baseline {bman.get(field)!r}")
    if spec.get("seeds") and list(man.get("seeds") or []) != list(spec["seeds"]):
        problems.append(f"manifest seeds {man.get('seeds')} != spec seeds {spec['seeds']}")

    # 4. Reported metrics must be what the rows say (a hand-edited summary over honest rows).
    if rows and not holes:
        ids = [m for m in graded if m in rows[0]]
        recomputed = aggregate([{**r, "cost": r.get("cost", 0.0)} for r in rows], ids,
                               k_values=spec.get("pass_k", []))
        reported = pr.get("metrics") or {}
        for k, v in recomputed.items():
            if k not in reported:
                continue    # a dropped blocking metric is caught as MISSING by check()
            got = reported[k]
            if isinstance(v, (int, float)) and isinstance(got, (int, float)) and abs(v - got) <= 1e-9:
                continue
            if v != got:
                problems.append(f"metric {k} reported {got!r}, rows give {v!r}")

    # 5. Slice membership is fixed by the label, so it must match the baseline item by item.
    def tags(rep: dict) -> dict[str, tuple[str, ...]]:
        out: dict[str, tuple[str, ...]] = {}
        for r in rep.get("rows") or []:
            out.setdefault(r.get("item_id"), tuple(sorted(r.get("slices") or [])))
        return out
    bt = tags(base)
    for item, t in sorted(tags(pr).items()):
        if item in bt and bt[item] != t:
            problems.append(f"slice tags of {item} changed: {list(bt[item])} -> {list(t)}")

    # 6. Ratchet: on the same eval-set version, thresholds may only get stricter.
    if base_spec is not None:
        problems += ratchet(spec, base_spec)
    return problems


def _looser(name: str, new: dict, old: dict) -> list[str]:
    """Compare one metric or slice rule (threshold fields flattened into one dict)."""
    out = []
    if old.get("blocking") and not new.get("blocking"):
        out.append(f"{name}: blocking -> non-blocking")
    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append(f"{name}: no_significant_drop removed")
    for key, looser in (("min", lambda n, o: n < o), ("max", lambda n, o: n > o),
                        ("max_increase", lambda n, o: n > o)):
        if key in old:
            if key not in new:
                out.append(f"{name}: {key} removed (was {old[key]})")
            elif looser(new[key], old[key]):
                out.append(f"{name}: {key} {old[key]} -> {new[key]}")
    return out


def ratchet(spec: dict, base_spec: dict) -> list[str]:
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []   # a new eval-set version starts a new baseline; thresholds may be reset there
    out = []
    flat = lambda m: {**(m.get("threshold") or {}), "blocking": m.get("blocking")}
    new_m = {m["id"]: m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        if m["id"] not in new_m:
            out.append(f"RATCHET metric {m['id']} removed")
        else:
            out += [f"RATCHET {p}" for p in _looser(m["id"], flat(new_m[m["id"]]), flat(m))]
    new_s = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        sid = f"slice:{s['name']}/{s['metric']}"
        if (s["name"], s["metric"]) not in new_s:
            out.append(f"RATCHET {sid} removed")
        else:
            out += [f"RATCHET {p}" for p in _looser(sid, new_s[(s["name"], s["metric"])], s)]
    ob, nb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if nb.get("confidence", 0.95) > ob.get("confidence", 0.95):
        out.append(f"RATCHET bootstrap confidence {ob.get('confidence', 0.95)} -> {nb.get('confidence')} (wider CI blocks less)")
    if list(spec.get("seeds") or []) != list(base_spec.get("seeds") or []):
        out.append(f"RATCHET seeds {base_spec.get('seeds')} -> {spec.get('seeds')}")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a = per_item(pr, metric, slice_name=name)       # item -> mean over seeds, this slice only
        b = per_item(base, metric, slice_name=name)
        verdict, note = "ok", ""
        val = round(sum(a.values()) / len(a), 4) if a else None
        if val is None:
            # an empty slice cannot be measured; relabelling items out of it must not read as a pass
            verdict, note = "missing", "no items in slice"
        elif "min" in s and val < s["min"]:
            verdict = "fail"
        if val is not None and s.get("no_significant_drop"):
            keys = sorted(set(a) & set(b))
            if keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                                                   confidence=bs.get("confidence", 0.95))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<34} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}  (n={len(a)} items)")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
