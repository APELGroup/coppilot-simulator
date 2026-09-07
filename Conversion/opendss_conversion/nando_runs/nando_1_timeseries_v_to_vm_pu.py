import re
import pandas as pd

# =========================
# SETTINGS
# =========================
IN_XLSX  = r"C:\Users\anton\Desktop\nando_pp\excels\Vdata_48steps.xlsx"   # <- αν αυτό είναι σε Volts
OUT_XLSX = r"C:\Users\anton\Desktop\nando_pp\excels\vm_pu_1ph_equivalent.xlsx"

SHEET_IN = 0  # ή "Voltages" / "vm_pu"
VBASE = 230.9

# Αν ξέρεις σίγουρα ότι το input είναι Volts: force_input_volts=True
# Αν ξέρεις σίγουρα ότι το input είναι pu: force_input_volts=False
# Αν δεν είσαι σίγουρος: None (auto-detect)
force_input_volts = None

# =========================
# LOAD
# =========================
df = pd.read_excel(IN_XLSX, sheet_name=SHEET_IN)

# index
if "timestep" in df.columns:
    df = df.set_index("timestep")
else:
    first = df.columns[0]
    if str(first).lower().startswith("unnamed"):
        df = df.set_index(first)

df = df.apply(pd.to_numeric, errors="coerce")

# =========================
# AUTO-DETECT Volts vs pu (or force)
# =========================
# heuristic: if median value > 2.0, it's probably Volts (e.g. ~230)
sample = df.stack().dropna()
median_val = float(sample.median()) if len(sample) else 1.0

if force_input_volts is None:
    input_is_volts = (median_val > 2.0)
else:
    input_is_volts = bool(force_input_volts)

if input_is_volts:
    df_pu = df / VBASE
else:
    df_pu = df

print(f"Median value in file: {median_val:.3f} -> treating input as {'VOLTS' if input_is_volts else 'PU'}")
print(f"Using Vbase={VBASE} V")

# =========================
# BUILD 1-PH EQUIVALENT (mean of available phases)
# =========================
pat = re.compile(r"^(.*)\.(1|2|3)$")

bus_to_cols = {}
for col in df_pu.columns:
    m = pat.match(str(col).strip())
    if not m:
        continue
    bus = m.group(1)
    ph  = int(m.group(2))
    bus_to_cols.setdefault(bus, {})[ph] = col

eq = {}
for bus, phcols in bus_to_cols.items():
    cols = [phcols[p] for p in sorted(phcols.keys())]  # available phases
    eq[bus] = df_pu[cols].mean(axis=1)                 # 3φ->mean, 1φ->itself, 2φ->mean

vm_pu_1ph = pd.DataFrame(eq, index=df_pu.index)

# =========================
# EXPORT (sheet name vm_pu)
# =========================
with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
    vm_pu_1ph.to_excel(writer, sheet_name="vm_pu", index_label="timestep")

print(f"Saved: {OUT_XLSX} (sheet: vm_pu)")
print(f"Shape: {vm_pu_1ph.shape[0]} timesteps x {vm_pu_1ph.shape[1]} buses")
