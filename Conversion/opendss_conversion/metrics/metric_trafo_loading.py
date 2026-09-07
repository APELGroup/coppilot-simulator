import sys
import pandas as pd
import numpy as np
import re
from pathlib import Path
from pandapower import from_excel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# =========================
# PATHS / SETTINGS  (from config.py)
# =========================
NET_XLSX     = str(config.NET_PP_XLSX)
PP_TRAFO_CSV = str(config.RESULTS_RES_TRAFO / "loading_percent.csv")
DSS_XLSX     = str(config.DSS_TRAFO_LOADING_XLSX)
DSS_SHEET    = config.DSS_TRAFO_LOADING_SHEET

OUT_XLSX   = str(config.METRICS_OUT_DIR / "trafo_loading_compare.xlsx")
DEBUG_XLSX = str(config.RESULTS_DIR  / "trafo_loading_debug.xlsx")

SEP = ";"

# =========================
# NAME NORMALIZER
# =========================
def norm_name(x: str) -> str:
    s = str(x).strip().lower()
    s = re.sub(r"^transformer\.", "", s)
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s

# =========================
# 1) Load net
# =========================
net = from_excel(NET_XLSX)
net.trafo["name"] = net.trafo["name"].astype(str)

# =========================
# 2) Read PP loading_percent.csv
# =========================
pp = pd.read_csv(PP_TRAFO_CSV, sep=SEP, engine="python")
if "time_step" in pp.columns:
    pp = pp.set_index("time_step")
else:
    pp = pp.set_index(pp.columns[0])

pp = pp.apply(pd.to_numeric, errors="coerce")
pp.columns = [str(c).strip() for c in pp.columns]

# =========================
# 3) Read DSS loading excel
# =========================
dss = pd.read_excel(DSS_XLSX, sheet_name=DSS_SHEET)

# keep whatever index it has; we will ALIGN BY POSITION anyway
if "timestamp" in dss.columns:
    dss["timestamp"] = pd.to_datetime(dss["timestamp"], errors="coerce")
    dss = dss.set_index("timestamp")
elif "time_step" in dss.columns:
    dss = dss.set_index("time_step")
elif "timestep" in dss.columns:
    dss = dss.set_index("timestep")
else:
    first = dss.columns[0]
    if str(first).lower().startswith("unnamed"):
        dss = dss.set_index(first)

dss = dss.apply(pd.to_numeric, errors="coerce")

# =========================
# 4) DSS normalized map
# =========================
dss_norm_map = {}
dss_collisions = []
for c in dss.columns:
    k = norm_name(c)
    if k in dss_norm_map and dss_norm_map[k] != c:
        dss_collisions.append({"norm_key": k, "col_1": dss_norm_map[k], "col_2": c})
    else:
        dss_norm_map[k] = c

# =========================
# 5) Compare trafos (ALIGN BY POSITION)
# =========================
summary_cols = ["trafo_name", "pp_trafo_idx", "dss_col", "N", "MAE_pp", "RMSE_pp", "Bias_pp", "MaxAbs_pp"]
rows = []
diff_df = pd.DataFrame()  # timeseries diffs per trafo (RangeIndex)

debug_rows = []

matched = 0
skipped_no_pp = 0
skipped_no_dss = 0
skipped_no_data = 0

# for "overall mean diff per timestep" across ALL matched trafos
global_diff_sums = None   # np.array length = n_steps
global_diff_counts = None # np.array length = n_steps

for trafo_idx, trafo_name in net.trafo["name"].items():
    pp_col = str(trafo_idx)
    if pp_col not in pp.columns:
        skipped_no_pp += 1
        continue

    k = norm_name(trafo_name)
    if k not in dss_norm_map:
        skipped_no_dss += 1
        debug_rows.append({
            "trafo_idx": trafo_idx,
            "pp_net_name": trafo_name,
            "norm_key": k,
            "status": "NO_DSS_MATCH"
        })
        continue

    dss_col = dss_norm_map[k]

    s_pp = pp[pp_col].to_numpy(dtype=float)
    s_dss = dss[dss_col].to_numpy(dtype=float)

    n = min(len(s_pp), len(s_dss))
    if n == 0:
        skipped_no_data += 1
        debug_rows.append({
            "trafo_idx": trafo_idx,
            "pp_net_name": trafo_name,
            "norm_key": k,
            "matched_dss_col": str(dss_col),
            "status": "NO_DATA_LEN0"
        })
        continue

    a_pp = s_pp[:n]
    a_dss = s_dss[:n]

    mask = (~np.isnan(a_pp)) & (~np.isnan(a_dss))
    if not np.any(mask):
        skipped_no_data += 1
        debug_rows.append({
            "trafo_idx": trafo_idx,
            "pp_net_name": trafo_name,
            "norm_key": k,
            "matched_dss_col": str(dss_col),
            "status": "NO_DATA_AFTER_NAN_MASK"
        })
        continue

    diff_pp_full = a_pp - a_dss  # p.p. (may contain NaNs)
    diff_pp = diff_pp_full[mask] # compact for per-trafo summary metrics

    matched += 1

    # store per-trafo diff (keep NaNs in original positions for per-timestep averaging)
    col_series = pd.Series(diff_pp_full, index=pd.RangeIndex(n), name=trafo_name)
    diff_df = pd.concat([diff_df, col_series], axis=1)

    rows.append({
        "trafo_name": trafo_name,
        "pp_trafo_idx": trafo_idx,
        "dss_col": str(dss_col),
        "N": int(diff_pp.size),
        "MAE_pp": float(np.mean(np.abs(diff_pp))),
        "RMSE_pp": float(np.sqrt(np.mean(diff_pp ** 2))),
        "Bias_pp": float(np.mean(diff_pp)),
        "MaxAbs_pp": float(np.max(np.abs(diff_pp))),
    })

    # accumulate global per-timestep mean (ignore NaNs)
    if global_diff_sums is None:
        global_diff_sums = np.zeros(n, dtype=float)
        global_diff_counts = np.zeros(n, dtype=int)
    else:
        # ensure same length by trimming to the smallest seen so far
        m = min(len(global_diff_sums), n)
        global_diff_sums = global_diff_sums[:m]
        global_diff_counts = global_diff_counts[:m]
        diff_pp_full = diff_pp_full[:m]
        mask = mask[:m]

    global_diff_sums[mask] += diff_pp_full[mask]
    global_diff_counts[mask] += 1

    debug_rows.append({
        "trafo_idx": trafo_idx,
        "pp_net_name": trafo_name,
        "norm_key": k,
        "matched_dss_col": str(dss_col),
        "n_steps_used": int(len(global_diff_sums)),
        "used_after_mask": int(diff_pp.size),
        "status": "MATCH_OK_POSITION_ALIGN"
    })

summary = pd.DataFrame(rows, columns=summary_cols)

# =========================
# 6) GLOBAL MEANS
#   a) global summary row (mean of per-trafo metrics)
#   b) global mean difference timeseries (per timestep across trafos)
# =========================
global_mean_ts = None
if global_diff_sums is not None:
    with np.errstate(divide="ignore", invalid="ignore"):
        global_mean_ts = global_diff_sums / np.where(global_diff_counts == 0, np.nan, global_diff_counts)
    global_mean_ts = pd.Series(global_mean_ts, index=pd.RangeIndex(len(global_mean_ts)), name="GLOBAL_MEAN_DIFF_pp")

if not summary.empty:
    summary = summary.sort_values("MAE_pp", ascending=False).reset_index(drop=True)

    global_row = pd.DataFrame([{
        "trafo_name": "=== GLOBAL MEAN (all matched trafos) ===",
        "pp_trafo_idx": "",
        "dss_col": "",
        "N": int(summary["N"].sum()),
        "MAE_pp": float(summary["MAE_pp"].mean()),
        "RMSE_pp": float(summary["RMSE_pp"].mean()),
        "Bias_pp": float(summary["Bias_pp"].mean()),
        "MaxAbs_pp": float(summary["MaxAbs_pp"].max()),
    }], columns=summary_cols)

    summary = pd.concat([global_row, summary], ignore_index=True)

# also prepare a separate sheet that includes the global mean timeseries alongside per-trafo diffs
diff_with_global = diff_df.copy()
if global_mean_ts is not None:
    diff_with_global.insert(0, "GLOBAL_MEAN_DIFF_pp", global_mean_ts.reindex(diff_with_global.index))
# =========================
# SINGLE GLOBAL NUMBER (overall MAE in p.p.)
# =========================
overall_mae_pp = None
overall_rmse_pp = None

if not diff_df.empty:
    # flatten all diffs (ignore NaNs)
    all_diffs = diff_df.to_numpy().flatten()
    all_diffs = all_diffs[~np.isnan(all_diffs)]
    if all_diffs.size > 0:
        overall_mae_pp = float(np.mean(np.abs(all_diffs)))
        overall_rmse_pp = float(np.sqrt(np.mean(all_diffs ** 2)))

print("=======================================")
if overall_mae_pp is not None:
    print(f"OVERALL MEAN ABS DIFFERENCE (p.p.): {overall_mae_pp:.4f}")
    print(f"OVERALL RMSE (p.p.): {overall_rmse_pp:.4f}")
else:
    print("OVERALL MEAN ABS DIFFERENCE: Not available")
    print("OVERALL RMSE: Not available")
# =========================
# 7) Export
# =========================
with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
    summary.to_excel(writer, index=False, sheet_name="summary")
    diff_with_global.to_excel(writer, sheet_name="diff_timeseries_pp")

debug_df = pd.DataFrame(debug_rows)
coll_df = pd.DataFrame(dss_collisions)

with pd.ExcelWriter(DEBUG_XLSX, engine="openpyxl") as writer:
    debug_df.to_excel(writer, index=False, sheet_name="mapping_debug")
    coll_df.to_excel(writer, index=False, sheet_name="dss_norm_collisions")

print("=======================================")
print("DONE")
print(f"Matched trafos: {matched}")
print(f"Skipped (no PP column): {skipped_no_pp}")
print(f"Skipped (no DSS match): {skipped_no_dss}")
print(f"Skipped (no usable data): {skipped_no_data}")
if global_mean_ts is not None:
    print(f"Global mean timeseries length: {len(global_mean_ts)}")
print(f"Saved summary: {OUT_XLSX}")
print(f"Saved debug:   {DEBUG_XLSX}")