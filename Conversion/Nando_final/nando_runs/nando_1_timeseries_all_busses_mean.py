import pandas as pd

# Load CSV
in_path = r"C:\Users\anton\Desktop\nando_pp\excels\Vdata_all_buses_clean.csv"
df = pd.read_csv(in_path)
df = df.set_index("timestep")

# =========================
# Group by base bus
# =========================
bus_groups = {}

for col in df.columns:
    base_bus = col.split(".")[0]
    bus_groups.setdefault(base_bus, []).append(col)

# =========================
# Compute mean per bus (NO fragmentation)
# =========================
result = {}

for bus, cols in bus_groups.items():
    if len(cols) == 3:
        result[bus] = df[cols].mean(axis=1)
    else:
        result[bus] = df[cols[0]]

# Create dataframe ONCE
df_mean = pd.DataFrame(result)

# =========================
# Save
# =========================
out_path = r"C:\Users\anton\Desktop\nando_pp\excels\Vdata_mean_per_bus.csv"
df_mean.to_csv(out_path)

print(f"Saved averaged voltages to: {out_path}")