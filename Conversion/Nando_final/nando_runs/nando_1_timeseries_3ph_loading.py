"""
nando_runs/nando_1_timeseries_3ph_loading.py

Run OpenDSS daily timeseries (48 steps × 30 min) and collect
per-phase loading (%) for ALL lines and ALL transformers.

The circuit is compiled directly from dss_files/Master.dss
(no DSSDriver / NetworkData / Excel dependency).

Output CSVs  (sep=";", index=time_step, columns=dss_element_name):
    excels/dss_line_loading_a_percent.csv
    excels/dss_line_loading_b_percent.csv
    excels/dss_line_loading_c_percent.csv
    excels/dss_trafo_loading_a_percent.csv
    excels/dss_trafo_loading_b_percent.csv
    excels/dss_trafo_loading_c_percent.csv
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

try:
    import dss as dss_lib
    print(f"dss_python {dss_lib.__version__}", file=sys.stderr)
except ModuleNotFoundError:
    raise ModuleNotFoundError(
        "Module 'dss_python' not found.  "
        "Install via: pip install dss_python==0.12.1"
    )

NPTS = 48
_PHASE_IDX = {1: 0, 2: 1, 3: 2}   # DSS node number → 0-based phase (0=A,1=B,2=C)
_PH_LABELS = ("a", "b", "c")


# ──────────────────────────────────────────────────────────────────────────────
def _parse_phases(bus_str: str):
    """Return sorted list of 0-based phase indices from a DSS bus string.

    Examples:
        "busname.1.2.3" → [0, 1, 2]
        "busname.2"     → [1]
        "busname"       → [0]   (default: phase 1 = A)
    """
    parts = bus_str.lower().split(".")
    nodes = []
    for p in parts[1:]:
        if p.isdigit():
            n = int(p)
            idx = _PHASE_IDX.get(n)
            if idx is not None and idx not in nodes:
                nodes.append(idx)
    return sorted(nodes) if nodes else [0]


# ──────────────────────────────────────────────────────────────────────────────
def main():
    np.random.seed(config.SEED)

    # ── 1. Compile Master.dss ──────────────────────────────────────────────
    dss     = dss_lib.DSS
    dss.Start(0)
    text    = dss.Text
    circuit = dss.ActiveCircuit
    sol     = circuit.Solution

    master = str(config.DSS_DIR / "Master.dss")
    # Compile changes CWD to the DSS dir so relative Redirects work
    text.Command = f'Compile "{master}"'
    print(f"[OK] Compiled {master}")

    # ── 2. Daily mode ──────────────────────────────────────────────────────
    text.Command = "Set Mode=daily number=1 stepsize=30m"
    text.Command = "Set time=(0,0)"

    # ── 3. Collect static element info ────────────────────────────────────
    all_lines  = list(circuit.Lines.AllNames)
    all_trafos = list(circuit.Transformers.AllNames)
    print(f"[INFO] Lines: {len(all_lines)}  –  Trafos: {len(all_trafos)}")

    # --- Lines: ampacity (normamps) and phase assignment ---
    line_info = {}
    for ln in all_lines:
        circuit.Lines.Name = ln
        try:
            amp = float(circuit.ActiveElement.Properties("normamps").Val)
        except Exception:
            amp = np.nan
        bus1   = circuit.ActiveElement.Properties("bus1").Val
        phases = _parse_phases(bus1)
        line_info[ln] = {"normamps": amp, "phases": phases}

    # --- Trafos: normamps, conductors-per-winding, and phase assignment via NodeOrder ---
    trafo_info = {}
    for tx in all_trafos:
        circuit.Transformers.Name = tx
        try:
            nph = int(circuit.ActiveElement.Properties("phases").Val)
        except Exception:
            nph = 1
        try:
            normamps = float(circuit.ActiveElement.Properties("normamps").Val)
        except Exception:
            normamps = np.nan
        # NodeOrder returns node numbers (1=A,2=B,3=C,0=neutral) for every conductor
        # of every winding concatenated.  Each winding has (nph+1) entries (incl. neutral).
        node_order = list(circuit.ActiveElement.NodeOrder)
        n_cond = nph + 1            # conductors per winding (including neutral node)
        winding1_nodes = node_order[:n_cond]
        # map non-zero nodes to 0-based phase index: 1→0(A), 2→1(B), 3→2(C)
        ph_assignments = [
            (k, node - 1)
            for k, node in enumerate(winding1_nodes)
            if node > 0
        ]
        # ph_assignments has 2 entries and no neutral in winding1 → line-to-line HV
        is_line_to_line    = (nph == 1) and (0 not in winding1_nodes)
        # 1-phase Wye-Wye (pole-top): phase-to-neutral on HV, only phase A in PP
        # → PP solver diverges for the 3-phase Dyn representation → exclude from metrics
        is_single_phase_yy = (nph == 1) and (0 in winding1_nodes)
        # For 1-phase trafos DSS uses normamps = kVA/kV (no √3),
        # but pandapower always uses i_rated = S/(√3·V).
        # Divide normamps by √3 for 1-phase so both tools share the same base.
        if nph == 1:
            normamps = normamps / np.sqrt(3)
        trafo_info[tx] = {
            "normamps": normamps,
            "n_cond": n_cond,
            "ph_assignments": ph_assignments,
            "is_line_to_line": is_line_to_line,
            "is_single_phase_yy": is_single_phase_yy,
        }

    # ── 4. Allocate result arrays (numpy, convert to DataFrame at end) ──────
    n_lines  = len(all_lines)
    n_trafos = len(all_trafos)
    line_arr  = {ph: np.full((NPTS, n_lines),  np.nan) for ph in _PH_LABELS}
    trafo_arr = {ph: np.full((NPTS, n_trafos), np.nan) for ph in _PH_LABELS}

    # ── 5. Timeseries loop ────────────────────────────────────────────────
    for t in tqdm(range(NPTS), desc="DSS 3ph loading"):
        sol.Solve()

        # ---- Lines -------------------------------------------------------
        for i, ln in enumerate(all_lines):
            circuit.Lines.Name = ln
            info = line_info[ln]
            amp  = info["normamps"]
            if np.isnan(amp) or amp <= 0:
                continue
            currents = circuit.ActiveElement.CurrentsMagAng
            for k, ph_idx in enumerate(info["phases"]):
                c_idx = 2 * k
                if c_idx < len(currents):
                    line_arr[_PH_LABELS[ph_idx]][t, i] = currents[c_idx] / amp * 100.0

        # ---- Trafos ------------------------------------------------------
        for j, tx in enumerate(all_trafos):
            circuit.Transformers.Name = tx
            info     = trafo_info[tx]
            normamps = info["normamps"]
            if np.isnan(normamps) or normamps <= 0:
                continue
            currents = circuit.ActiveElement.CurrentsMagAng
            for k, ph_idx in info["ph_assignments"]:
                c_idx = 2 * k
                if c_idx < len(currents):
                    trafo_arr[_PH_LABELS[ph_idx]][t, j] = currents[c_idx] / normamps * 100.0

    # ── 6. Save CSVs ──────────────────────────────────────────────────────
    out_dir = config.EXCELS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save line-to-line trafo names (excluded from PP loading metrics)
    ll_names = [tx for tx, info in trafo_info.items() if info["is_line_to_line"]]
    pd.Series(ll_names, name="trafo_name").to_csv(
        config.DSS_TRAFO_LL_NAMES, index=False
    )
    print(f"[INFO] Line-to-line trafos: {len(ll_names)} -> {config.DSS_TRAFO_LL_NAMES.name}")

    # Save 1-phase Wye-Wye (pole-top) trafo names (excluded from PP loading metrics)
    yy_names = [tx for tx, info in trafo_info.items() if info["is_single_phase_yy"]]
    pd.Series(yy_names, name="trafo_name").to_csv(
        config.DSS_TRAFO_1PH_YY_NAMES, index=False
    )
    print(f"[INFO] 1-phase Yy trafos:   {len(yy_names)} -> {config.DSS_TRAFO_1PH_YY_NAMES.name}")

    for ph in _PH_LABELS:
        df = pd.DataFrame(line_arr[ph], index=range(NPTS), columns=all_lines)
        df.index.name = "time_step"
        fp = out_dir / f"dss_line_loading_{ph}_percent.csv"
        df.to_csv(fp, sep=";")
        print(f"[OK] {fp.name}")

        df = pd.DataFrame(trafo_arr[ph], index=range(NPTS), columns=all_trafos)
        df.index.name = "time_step"
        fp = out_dir / f"dss_trafo_loading_{ph}_percent.csv"
        df.to_csv(fp, sep=";")
        print(f"[OK] {fp.name}")

    print("[DONE] DSS 3ph loading timeseries complete.")


if __name__ == "__main__":
    main()
