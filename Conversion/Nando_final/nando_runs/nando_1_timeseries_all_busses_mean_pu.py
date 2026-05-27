import pandas as pd
import numpy as np

# =========================
# 1. Load CSV
# =========================
in_path = r"C:\Users\anton\Desktop\nando_pp\excels\Vdata_all_nodes_48steps.csv"
df = pd.read_csv(in_path)
df = df.set_index("timestep")

# =========================
# 2. Group by base bus
# =========================
bus_groups = {}

for col in df.columns:
    base_bus = col.split(".")[0]
    bus_groups.setdefault(base_bus, []).append(col)

# =========================
# 3. Base voltages
# =========================
SOURCE_BASE = 66000 / np.sqrt(3)   # ~38105.12 V
MV_BASE = 22000 / np.sqrt(3)       # ~12701.71 V
LV_BASE = 400 / np.sqrt(3)         # ~230.94 V

# =========================
# 4. Mean per bus + vm_pu
# =========================
result = {}

for bus, cols in bus_groups.items():

    # mean per bus
    if len(cols) == 3:
        v_mean = df[cols].mean(axis=1)
    else:
        v_mean = df[cols[0]]

    bus_lower = bus.lower()

    # choose correct base voltage
    if "source" in bus_lower:
        v_base = SOURCE_BASE
    elif "lv" in bus_lower:
        v_base = LV_BASE
    else:
        v_base = MV_BASE

    # convert to pu
    result[bus] = v_mean / v_base

# Create dataframe once
df_vm_pu = pd.DataFrame(result)

# =========================
# 5. Save
# =========================
out_path = r"C:\Users\anton\Desktop\nando_pp\excels\Vmean_vm_pu_with_source.csv"
df_vm_pu.to_csv(out_path)

print(f"Saved vm_pu mean per bus to: {out_path}")