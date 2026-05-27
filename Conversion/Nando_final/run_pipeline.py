"""
run_pipeline.py  –  Full OpenDSS → pandapower pipeline runner.

Steps:
  1. dss_files_creator      → generate all .dss files from Excel
  2. dss_to_pp_mv_build     → build MV pandapower network → dss_files/mv_net.xlsx
  3. dss_to_pp_lv_build     → add LV trafos & lines    → dss_files/net_pp.xlsx
  4. prepare_net_for_3ph    → zero-seq + asymmetric loads → dss_files/net_pp_3ph_ready.xlsx
  5a. pp_timeseries          → balanced 48-step timeseries  → results/res_bus/, res_line/, ...
  5b. pp_timeseries_3ph      → 3-phase 48-step timeseries   → results/res_bus_3ph/
  6. nando_runs (OpenDSS reference simulations – configurable below)
  7. metrics/metrics_vm_pu   → compare PP vs DSS voltages    → metrics/

Edit config.py (project root) to change NETWORK_OPTION, paths, etc.
"""

import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.resolve()


# ─── PIPELINE STEPS ───────────────────────────────────────────────────────────
# Each entry: (script_path_relative_to_ROOT, step_label, enabled)
# Set enabled=False to skip a step.

STEPS = [
    ("conversion/dss_files_creator.py",    "1. Generate DSS files from Excel",          True),
    ("conversion/dss_to_pp_mv_build.py",   "2. Build MV pandapower network",            True),
    ("conversion/dss_to_pp_lv_build.py",   "3. Add LV network (trafos + lines)",        True),
    ("fixes/prepare_net_for_3ph.py",       "4. Prepare 3-phase network",                False),
    ("panda_runs/pp_timeseries.py",        "5a. Run balanced timeseries (pandapower)",   True),
    ("panda_runs/pp_timeseries_3ph.py",    "5b. Run 3-phase timeseries (pandapower)",   False),
    # ── OpenDSS reference simulations (nando_runs) ──────────────────────────
    # Balanced: all buses (clean + mean pu) + all lines loading
    ("nando_runs/nando_run_balanced.py",   "6a. OpenDSS – balanced (buses + lines)",             False),
    # Unbalanced (3-phase): per-phase line + trafo loading
    ("nando_runs/nando_run_unbalanced.py", "6b. OpenDSS – unbalanced 3ph (lines + trafos)",      False),
    # ── Metrics (PP vs DSS) ───────────────────────────────────────────────
    ("metrics/metrics_all_busses.py",      "7a. Metrics – all buses (vm_pu, balanced)",          False),
    ("metrics/metrics_3ph_vm_pu.py",       "7b. Metrics – bus voltages (3-phase vs DSS)",        False),
    ("metrics/metrics_3ph_loading.py",     "7c. Metrics – line+trafo loading (3-phase vs DSS)",  True),
    ("metrics/metrics_all_lines.py",       "7d. Metrics – all lines loading",                    False),
    ("metrics/metric_trafo_loading.py",    "7e. Metrics – trafo loading",                        True),
]
# ──────────────────────────────────────────────────────────────────────────────


def _separator(label: str):
    print(f"\n{'=' * 65}")
    print(f"  {label}")
    print(f"{'=' * 65}")


def run_step(script_rel: str, label: str):
    script = ROOT / script_rel
    if not script.exists():
        raise FileNotFoundError(f"Script not found: {script}")
    _separator(label)
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Step failed with exit code {result.returncode}:\n  {script}"
        )
    print(f"\n✓  {label}")


def main():
    print(f"\nNando_pp pipeline  –  root: {ROOT}")

    failed = []
    for script_rel, label, enabled in STEPS:
        if not enabled:
            print(f"\n  [SKIP] {label}")
            continue
        try:
            run_step(script_rel, label)
        except Exception as exc:
            failed.append((label, exc))
            print(f"\n✗  {label}\n   ERROR: {exc}")
            # continue running remaining steps so you see all failures at once
            continue

    print(f"\n{'=' * 65}")
    if failed:
        print(f"Pipeline finished with {len(failed)} error(s):")
        for lbl, exc in failed:
            print(f"  ✗  {lbl}")
        sys.exit(1)
    else:
        print("Pipeline completed successfully.")


if __name__ == "__main__":
    main()
