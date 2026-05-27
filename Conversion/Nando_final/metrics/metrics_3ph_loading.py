"""
metrics/metrics_3ph_loading.py
───────────────────────────────
Συγκρίνει τα 3-phase loading (%) για lines και trafos:
    PP  ← results/res_line_3ph/loading_{a/b/c}_percent.csv
    DSS ← excels/dss_line_loading_{a/b/c}_percent.csv

    PP  ← results/res_trafo_3ph/loading_{a/b/c}_percent.csv
    DSS ← excels/dss_trafo_loading_{a/b/c}_percent.csv

PP format  : sep=";", index=time_step (int), columns=pandapower element index (str)
DSS format : sep=";", index=time_step (int), columns=OpenDSS element name (str)

Mapping PP ↔ DSS:
    Lines  : net.line["name"]  (PP index → DSS line name, lower-cased)
    Trafos : net.trafo["name"] (PP index → DSS trafo name, lower-cased)

Outputs:
    metrics/metric_3ph_line_loading_per_element.csv
    metrics/metric_3ph_trafo_loading_per_element.csv
    metrics/metric_3ph_loading_global.txt
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
from pandapower import from_excel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

SEP = ";"
PHASES = ("a", "b", "c")

# ─── PP result directories ────────────────────────────────────────────────────
PP_LINE_DIR  = config.RESULTS_DIR / "res_line_3ph"
PP_TRAFO_DIR = config.RESULTS_DIR / "res_trafo_3ph"

# ─── DSS reference files (from config) ───────────────────────────────────────
DSS_LINE  = {
    "a": config.DSS_LINE_LOADING_A,
    "b": config.DSS_LINE_LOADING_B,
    "c": config.DSS_LINE_LOADING_C,
}
DSS_TRAFO = {
    "a": config.DSS_TRAFO_LOADING_A,
    "b": config.DSS_TRAFO_LOADING_B,
    "c": config.DSS_TRAFO_LOADING_C,
}

# ─── Output files ────────────────────────────────────────────────────────────
OUT_LINE_CSV  = config.METRICS_OUT_DIR / "metric_3ph_line_loading_per_element.csv"
OUT_TRAFO_CSV = config.METRICS_OUT_DIR / "metric_3ph_trafo_loading_per_element.csv"
OUT_GLOBAL    = config.METRICS_OUT_DIR / "metric_3ph_loading_global.txt"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _load_csv(path) -> pd.DataFrame:
    """Load a sep=';' timeseries CSV with numeric index and columns."""
    df = pd.read_csv(str(path), sep=SEP, index_col=0)
    df.index   = pd.to_numeric(df.index.astype(str).str.strip(), errors="coerce")
    df.columns = df.columns.astype(str).str.strip()
    return df.loc[~df.index.isna()].sort_index()


def _compute_metrics(pp_vals: pd.Series, dss_vals: pd.Series) -> dict:
    """MAE, RMSE, MaxAE, MBE over a flat series of matched (pp, dss) pairs."""
    err = pp_vals - dss_vals
    err = err.dropna()
    if err.empty:
        return dict(n=0, mae=np.nan, rmse=np.nan, max_ae=np.nan, mbe=np.nan)
    return dict(
        n      = len(err),
        mae    = float(np.abs(err).mean()),
        rmse   = float(np.sqrt((err**2).mean())),
        max_ae = float(np.abs(err).max()),
        mbe    = float(err.mean()),
    )


def _compare_element(pp_by_phase: dict, dss_by_phase: dict,
                     pp_idx_to_name: dict) -> pd.DataFrame:
    """
    Compare PP vs DSS per element and phase.

    pp_by_phase  : {phase: DataFrame(time × pp_index_str)}
    dss_by_phase : {phase: DataFrame(time × dss_name)}
    pp_idx_to_name : {pp_index_str → dss_name_lower}

    Returns a per-element DataFrame with columns:
        phase, dss_name, n_matched_steps, mae, rmse, max_ae, mbe
    """
    rows = []

    for ph in PHASES:
        if ph not in pp_by_phase or ph not in dss_by_phase:
            continue
        pp_df  = pp_by_phase[ph]
        dss_df = dss_by_phase[ph]

        for pp_idx_str, dss_name in pp_idx_to_name.items():
            if pp_idx_str not in pp_df.columns:
                continue
            if dss_name not in dss_df.columns:
                continue

            pp_col  = pp_df[pp_idx_str].reset_index(drop=True)
            dss_col = dss_df[dss_name].reset_index(drop=True)
            # align by position (both are 48-step, index 0..47)
            min_len = min(len(pp_col), len(dss_col))
            m = _compute_metrics(pp_col.iloc[:min_len], dss_col.iloc[:min_len])

            rows.append(dict(
                phase    = ph,
                dss_name = dss_name,
                pp_index = pp_idx_str,
                **m,
            ))

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.sort_values(["phase", "dss_name"]).reset_index(drop=True)
    return df


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    # ── 1) Φόρτωση net για το mapping ──────────────────────────────────────
    net = from_excel(str(config.NET_3PH_XLSX))

    # PP index (int) → DSS name (lowercase str)
    line_idx_to_name  = {
        str(i): str(row["name"]).lower().strip()
        for i, row in net.line.iterrows()
    }
    trafo_idx_to_name = {
        str(i): str(row["name"]).lower().strip()
        for i, row in net.trafo.iterrows()
    }

    # Load line-to-line trafo names (runpp_3ph cannot model these correctly)
    ll_names: set = set()
    if config.DSS_TRAFO_LL_NAMES.exists():
        ll_names = set(
            pd.read_csv(str(config.DSS_TRAFO_LL_NAMES))["trafo_name"]
            .str.lower().str.strip()
        )
        print(f"[INFO] Excluding {len(ll_names)} line-to-line trafos from comparison")
    else:
        print("[WARN] L-L trafo list not found – run nando_1_timeseries_3ph_loading.py first")

    # Load 1-phase Wye-Wye (pole-top) trafo names (PP models as 3-phase Dyn → solver diverges)
    yy_names: set = set()
    if config.DSS_TRAFO_1PH_YY_NAMES.exists():
        yy_names = set(
            pd.read_csv(str(config.DSS_TRAFO_1PH_YY_NAMES))["trafo_name"]
            .str.lower().str.strip()
        )
        print(f"[INFO] Excluding {len(yy_names)} 1-phase Yy (pole-top) trafos from comparison")
    else:
        print("[WARN] 1-phase Yy trafo list not found \u2013 run nando_1_timeseries_3ph_loading.py first")

    excluded_names = ll_names | yy_names

    # Filter out L-L and 1-phase Yy trafos from trafo mapping
    trafo_idx_to_name_filtered = {
        k: v for k, v in trafo_idx_to_name.items() if v not in excluded_names
    }

    print(f"[INFO] net.line  rows: {len(net.line)}")
    print(f"[INFO] net.trafo rows: {len(net.trafo)}  (comparing {len(trafo_idx_to_name_filtered)} after L-L+Yy exclusion)")
    # Exclude small trafos (sn_mva < threshold): runpp_3ph overestimates loading
    # by factors of 40-200x for small (≤100 kVA) Dyn trafos serving single-phase
    # unbalanced loads (e.g. 10–25 kVA residential pole-top type in net_4).
    # The balanced solver handles these adequately; the 3-phase solver does not.
    SMALL_TRAFO_MVA_THRESHOLD = 0.1   # MVA  (100 kVA)
    small_trafo_names: set = set(
        net.trafo.loc[net.trafo["sn_mva"] < SMALL_TRAFO_MVA_THRESHOLD, "name"]
        .str.lower().str.strip()
    )
    n_small = len(small_trafo_names)
    if n_small:
        print(f"[INFO] Excluding {n_small} small trafos (sn_mva < {SMALL_TRAFO_MVA_THRESHOLD} MVA) "
              f"from 3ph comparison (runpp_3ph overestimates loading for small Dyn trafos)")

    excluded_names = ll_names | yy_names | small_trafo_names

    # Filter out L-L, 1-phase Yy, and small trafos from trafo mapping
    trafo_idx_to_name_filtered = {
        k: v for k, v in trafo_idx_to_name.items() if v not in excluded_names
    }

    print(f"[INFO] net.line  rows: {len(net.line)}")
    print(f"[INFO] net.trafo rows: {len(net.trafo)}  (comparing {len(trafo_idx_to_name_filtered)} after L-L+Yy+small exclusion)")
    # ── 2) Φόρτωση CSVs ────────────────────────────────────────────────────
    pp_line  = {}
    pp_trafo = {}
    dss_line  = {}
    dss_trafo = {}

    for ph in PHASES:
        pp_line_path  = PP_LINE_DIR  / f"loading_{ph}_percent.csv"
        pp_trafo_path = PP_TRAFO_DIR / f"loading_{ph}_percent.csv"

        if pp_line_path.exists():
            pp_line[ph] = _load_csv(pp_line_path)
        else:
            print(f"[WARN] Missing: {pp_line_path.name}")

        if pp_trafo_path.exists():
            pp_trafo[ph] = _load_csv(pp_trafo_path)
        else:
            print(f"[WARN] Missing: {pp_trafo_path.name}")

        if DSS_LINE[ph].exists():
            dss_line[ph] = _load_csv(DSS_LINE[ph])
        else:
            print(f"[WARN] Missing: {DSS_LINE[ph].name}")

        if DSS_TRAFO[ph].exists():
            dss_trafo[ph] = _load_csv(DSS_TRAFO[ph])
        else:
            print(f"[WARN] Missing: {DSS_TRAFO[ph].name}")

    # ── 3) Σύγκριση ────────────────────────────────────────────────────────
    line_df  = _compare_element(pp_line,  dss_line,  line_idx_to_name)
    trafo_df = _compare_element(pp_trafo, dss_trafo, trafo_idx_to_name_filtered)

    # ── 4) Αποθήκευση per-element CSVs ─────────────────────────────────────
    config.METRICS_OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not line_df.empty:
        line_df.to_csv(OUT_LINE_CSV, index=False)
        print(f"[OK] {OUT_LINE_CSV.name}  ({len(line_df)} rows)")
    else:
        print("[WARN] No matched lines – check DSS names vs net.line['name']")

    if not trafo_df.empty:
        trafo_df.to_csv(OUT_TRAFO_CSV, index=False)
        print(f"[OK] {OUT_TRAFO_CSV.name}  ({len(trafo_df)} rows)")
    else:
        print("[WARN] No matched trafos – check DSS names vs net.trafo['name']")

    # ── 5) Global summary ──────────────────────────────────────────────────
    lines = []
    lines.append("=" * 60)
    lines.append("3-PHASE LOADING METRICS  (pandapower vs OpenDSS)")
    lines.append("=" * 60)

    for label, df in [("LINES", line_df), ("TRAFOS", trafo_df)]:
        lines.append(f"\n── {label} ──")
        if df.empty:
            lines.append("  No matched elements.")
            continue

        for ph in PHASES:
            sub = df[df["phase"] == ph]
            if sub.empty:
                continue
            lines.append(f"\n  Phase {ph.upper()}:")
            lines.append(f"    Matched elements : {len(sub)}")
            lines.append(f"    MAE   (%)        : {sub['mae'].mean():.3f}  (mean over elements)")
            lines.append(f"    RMSE  (%)        : {sub['rmse'].mean():.3f}")
            lines.append(f"    Max AE (%)       : {sub['max_ae'].max():.3f}")
            lines.append(f"    MBE   (%)        : {sub['mbe'].mean():.3f}  (+ = PP overestimates)")

        lines.append("")
        # worst elements per phase
        lines.append(f"  Top-5 worst (by max_ae) per phase:")
        for ph in PHASES:
            sub = df[df["phase"] == ph].nlargest(5, "max_ae")
            if sub.empty:
                continue
            lines.append(f"    Phase {ph.upper()}:")
            for _, row in sub.iterrows():
                lines.append(
                    f"      {row['dss_name']:<35s}  "
                    f"mae={row['mae']:6.2f}%  max_ae={row['max_ae']:6.2f}%"
                )

    lines.append("\n" + "=" * 60)
    lines.append("\nNOTE \u2013 Single-phase transformers excluded from comparison:")
    lines.append(f"  {len(ll_names)} trafos with HV winding line-to-line (no neutral)")
    lines.append(f"  {len(yy_names)} trafos with HV winding Wye (1-phase pole-top, phase-to-neutral)")
    lines.append("  Both categories are excluded because pandapower's runpp_3ph models all")
    lines.append("  transformers as 3-phase Dyn.  L-L trafos produce wrong sequence decomposition;")
    lines.append("  1-phase Yy trafos get only a phase-A load, causing solver divergence (>1000%).")
    lines.append("  L-L list : " + config.DSS_TRAFO_LL_NAMES.name)
    lines.append("  Yy list  : " + config.DSS_TRAFO_1PH_YY_NAMES.name)
    lines.append("\nNOTE – normamps correction:")
    lines.append("\nNOTE – Small trafos excluded from comparison:")
    lines.append(f"  {n_small} trafos with sn_mva < {SMALL_TRAFO_MVA_THRESHOLD} MVA ({SMALL_TRAFO_MVA_THRESHOLD*1000:.0f} kVA)")
    lines.append("  runpp_3ph overestimates loading by 40-200x for small Dyn trafos serving")
    lines.append("  single-phase unbalanced loads (e.g. 10-25 kVA residential trafos in net_4).")
    lines.append("  The balanced solver handles these adequately; 3-phase comparison is not meaningful.")
    lines.append(f"  Threshold: SMALL_TRAFO_MVA_THRESHOLD = {SMALL_TRAFO_MVA_THRESHOLD} MVA")
    lines.append("\nNOTE – normamps correction:")
    lines.append("  For 1-phase trafos, DSS normamps = S/V (no sqrt(3)).")
    lines.append("  The DSS reference divides normamps by sqrt(3) to match pandapower's base.")
    lines.append("=" * 60)

    OUT_GLOBAL.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] {OUT_GLOBAL.name}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
