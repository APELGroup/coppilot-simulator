import pandas as pd


# =========================
# ΡΥΘΜΙΣΕΙΣ
# =========================
input_csv = r"C:\Users\anton\Desktop\nando_pp\excels\Vdata_48steps_all.csv"
output_csv = r"C:\Users\anton\Desktop\nando_pp\excels\Vdata_all_buses_clean.csv"

threshold = 100.0   # σβήνει στήλες που ΔΕΝ έχουν καμία τιμή > 100


# =========================
# ΦΟΡΤΩΣΗ
# =========================
df = pd.read_csv(input_csv, index_col=0)

print("Αρχικό shape:", df.shape)
print("Αρχικές στήλες:", len(df.columns))


# =========================
# ΚΡΑΤΑΜΕ ΜΟΝΟ ΣΤΗΛΕΣ
# ΠΟΥ ΕΧΟΥΝ max > threshold
# =========================
cols_to_keep = df.columns[df.max(numeric_only=True) > threshold]
df_clean = df[cols_to_keep]

cols_removed = [c for c in df.columns if c not in cols_to_keep]

print("Στήλες που αφαιρέθηκαν:", len(cols_removed))
print("Νέο shape:", df_clean.shape)

if cols_removed:
    print("\nΠρώτες 30 στήλες που αφαιρέθηκαν:")
    for c in cols_removed[:900]:
        print(c)


# =========================
# ΑΠΟΘΗΚΕΥΣΗ
# =========================
df_clean.to_csv(output_csv)

print(f"\nΚαθαρό αρχείο αποθηκεύτηκε στο:\n{output_csv}")