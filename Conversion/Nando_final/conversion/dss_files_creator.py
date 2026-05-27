import os
import sys
import glob
import numpy as np
import pandas as pd
from itertools import permutations
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# =========================
# CONFIG  (values come from config.py – edit that file to change settings)
# =========================
NETWORK_OPTION = config.NETWORK_OPTION
EXPORT_DIR     = str(config.DSS_DIR)   # generated .dss files go to dss_files/
PROFILES_DIR   = "profiles"            # sub-folder inside EXPORT_DIR for CSVs
TIME_RES_MIN   = config.TIME_RES_MIN
SEED           = config.SEED
SELECTED_DAY   = config.SELECTED_DAY
RES_PROFILE_NPY = config.RES_PROFILE_NPY.name
COM_PROFILE_NPY = config.COM_PROFILE_NPY.name

# required networks
REQUIRED_XLSX = {
    "Network_1_Rural_SMR8.xlsx",
    "Network_2_Rural_KLO14.xlsx",
    "Network_3_Urban_HPK11.xlsx",
    "Network_4_Urban_CRE21.xlsx",
}


# =========================
# HELPERS
# =========================
class WrongNetworkNameError(Exception):
    pass

class MissingExcelSheetsError(Exception):
    pass

def check_data():
    cwd = str(config.EXCELS_DIR)

    networks = [n for n in os.listdir(cwd) if n.lower().endswith(".xlsx")]
    if set(networks) != REQUIRED_XLSX:
        missing = REQUIRED_XLSX - set(networks)
        extra = set(networks) - REQUIRED_XLSX
        raise MissingExcelSheetsError(
            f"Excel sheets mismatch.\nMissing: {sorted(missing)}\nExtra: {sorted(extra)}"
        )

    profiles = [n for n in os.listdir(cwd) if n.lower().endswith(".npy")]
    needed = {RES_PROFILE_NPY, COM_PROFILE_NPY}
    if set(profiles) & needed != needed:
        missing = needed - set(profiles)
        raise MissingExcelSheetsError(f"Profiles data missing: {sorted(missing)}")

def identify_network_xlsx(user_input: str) -> str:
    options = ["1", "2", "3", "4"]
    net_names = ["Network_1", "Network_2", "Network_3", "Network_4"]

    if str(user_input).upper() not in options:
        raise WrongNetworkNameError("Options are 1,2,3,4")

    cwd = str(config.EXCELS_DIR)
    prefix = net_names[options.index(str(user_input))]  # e.g. Network_1
    pattern = f"{cwd}/{prefix}_*.xlsx"
    matched = glob.glob(pattern)
    if not matched:
        raise MissingExcelSheetsError(f"No Excel matched {pattern}")
    return os.path.basename(matched[0])



def get_date_and_season(day_of_year: int):
    start_of_year = datetime(year=datetime.now().year, month=1, day=1)
    date = start_of_year + timedelta(days=day_of_year - 1)
    date_str = date.strftime("%B %d")

    # (όπως στον κώδικα σου)
    if 355 <= day_of_year or day_of_year <= 78:
        season = "Summer"
    elif 79 <= day_of_year <= 170:
        season = "Autumn"
    elif 171 <= day_of_year <= 263:
        season = "Winter"
    else:
        season = "Spring"
    return date_str, season

def char_to_num_map():
    three = [''.join(p) for p in permutations(['R', 'W', 'B'])]
    two = [''.join(p) for p in permutations(['R', 'B', 'W'], 2)]
    one = [''.join(p) for p in permutations(['R', 'B', 'W'], 1)]
    combos = three + two + one
    m = {k: '.'.join(str({'R': 1, 'W': 2, 'B': 3}[c]) for c in k) for k in combos}
    return m


# =========================
# DATA LOADER
# =========================
class NetworkData:
    def __init__(self, xlsx_path: str):
        self.xlsx_path = xlsx_path  # use the provided path (bug fix)
        self.data = {}
        self._load_all_sheets()

    def _load_all_sheets(self):
        xl = pd.ExcelFile(self.xlsx_path)
        for sh in xl.sheet_names:
            self.data[sh] = pd.read_excel(self.xlsx_path, sheet_name=sh)


# =========================
# EXPORTER
# =========================
class DSSExporter:
    def __init__(self, data: dict, export_dir: str):
        self.data = data
        self.export_dir = export_dir
        self.profiles_dir = os.path.join(export_dir, PROFILES_DIR)
        os.makedirs(self.export_dir, exist_ok=True)
        os.makedirs(self.profiles_dir, exist_ok=True)

        self.commands = {
            "01_Circuit.dss": [],
            "02_MV_NetTx.dss": [],
            "03_LineCodes.dss": [],
            "04_MV_Lines.dss": [],
            "05_Capacitors.dss": [],
            "06_Regulators.dss": [],
            "07_LV_Tx.dss": [],
            "08_LV_Lines.dss": [],
            "09_LoadShapes.dss": [],
            "10_Loads.dss": [],
        }
    def export_buscoords(self):
        if "buscoords" not in self.data:
            print("No 'buscoords' sheet found. Skipping BusCoords.csv")
            return

        bc = self.data["buscoords"].copy()

        # Προσαρμόζεις αυτά τα names αν στο Excel είναι αλλιώς
        # (εσύ ήδη έχεις Node_ID, NodeStartX, NodeStartY στον κώδικά σου)
        bc["Bus"] = bc["Node_ID"].apply(lambda v: f"mv_f0_n{v}")

        out = bc[["Bus", "NodeStartX", "NodeStartY"]].rename(
            columns={"NodeStartX": "X", "NodeStartY": "Y"}
        )

        out_path = os.path.join(self.export_dir, "BusCoords.csv")
        out.to_csv(out_path, index=False)
        print(f"Written: {out_path}")

    def _write_file(self, filename: str, lines: list[str]):
        path = os.path.join(self.export_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            for ln in lines:
                ln = ln.strip()
                if ln:
                    f.write(ln + "\n")

    def export_all(self, selected_day: int, seed: int):
        np.random.seed(seed)

        # selected_day logic
        if selected_day == 0:
            selected_day = int(np.random.randint(1, 366))  # 1..365
        date_str, season = get_date_and_season(selected_day)
        print(f"Selected day: {selected_day} -> {date_str} ({season})")
        self.export_buscoords()
        self.basic_and_source()
        self.mv_net_tx()
        self.line_codes()
        self.mv_lines()
        self.capacitors_optional()
        self.regulators_optional()
        self.lv_tx()
        self.lv_lines()
        self.loadshapes_and_loads(selected_day=selected_day, seed=seed)
        self.other_commands_master(note=f"Selected day {selected_day} -> {date_str} ({season})")

        # write all .dss files
        for fn, lines in self.commands.items():
            # μην γράφεις άδειο capacitor/regulator αν δεν έχει
            if fn in ("05_Capacitors.dss", "06_Regulators.dss") and len(lines) == 0:
                continue
            self._write_file(fn, lines)

        self._write_master()

        print(f"\nExport completed in: {os.path.abspath(self.export_dir)}")
        print("Open OpenDSS and Compile the Master.dss")

    def _write_master(self):
        master_lines = [
            "Clear",
            "Set DefaultBaseFrequency=50",
            "! --- Circuit / source",
            "Redirect 01_Circuit.dss",
            "",
            "! --- MV network",
            "Redirect 02_MV_NetTx.dss",
            "Redirect 03_LineCodes.dss",
            "Redirect 04_MV_Lines.dss",
        ]

        if os.path.exists(os.path.join(self.export_dir, "05_Capacitors.dss")):
            master_lines.append("Redirect 05_Capacitors.dss")
        if os.path.exists(os.path.join(self.export_dir, "06_Regulators.dss")):
            master_lines.append("Redirect 06_Regulators.dss")

        master_lines += [
            "",
            "! --- LV network",
            "Redirect 07_LV_Tx.dss",
            "Redirect 08_LV_Lines.dss",
            "Redirect 09_LoadShapes.dss",
            "Redirect 10_Loads.dss",
            "",
            "BusCoords BusCoords.csv",
            "! --- Post",
            "Set VoltageBases=[66.0, 22.0, 12.7, 0.400, 0.2309]",
            "CalcVoltageBases",
            "Solve",
        ]
        self._write_file("Master.dss", master_lines)

    # ---------- sections ----------
    def basic_and_source(self):
        # circuit / vsource
        self.commands["01_Circuit.dss"] += [
            "New Circuit.Circuit basekv=66 pu=1 angle=0 phases=3 R1=0.52824 X1=2.113 R0=0.59157 X0=1.7747",
            "Edit Vsource.Source bus1=sourcebus basekv=66 pu=1 angle=0 phases=3 R1=0.52824 X1=2.113 R0=0.59157 X0=1.7",
        ]

    def mv_net_tx(self):
        element = self.data["mv_net_txs"]
        for _, row in element.iterrows():
            cmd = (
                f"New Transformer.{row['Substation_ID']} "
                f"phases=3 windings=2 "
                f"buses=[{row['Bus1']}, mv_f0_n{row['Bus2']}] "
                f"conns=[{row['Connection_Primary']}, {row['Connection_Secondary']}] "
                f"kVs=[{row['kvs_primary']}, {row['kvs_secondary']}] "
                f"kVAs=[{row['kvas_primary']}, {row['kvas_secondary']}] "
                f"%loadloss={row['loadloss']} %noloadloss={row['noloadloss']} "
                f"xhl={row['xhl']} enabled=true"
            )
            self.commands["02_MV_NetTx.dss"].append(cmd)

    def line_codes(self):
        element = self.data["linecodes"]
        for _, row in element.iterrows():
            cmd = (
                f"New Linecode.lc_{row['Linecode_ID']} "
                f"nphases={row['Phases']} "
                f"r1={row['r1']} x1={row['x1']} b1={row['b1']} "
                f"r0={row['r0']} x0={row['x0']} b0={row['b0']} "
                f"units={row['Units']} normamp={min(row['Ampacity1'], row['Ampacity2'])}"
            )
            self.commands["03_LineCodes.dss"].append(cmd)

    def mv_lines(self):
        element = self.data["lines"]
        for _, row in element.iterrows():
            if str(row["Element_Name"]).lower() == "delete":
                continue
            cmd = (
                f"New Line.mv_f0_l{row['Line_Number']} "
                f"bus1=mv_f0_n{row['Start_Node']}.{row['Start_Node_Phase']} "
                f"bus2=mv_f0_n{row['End_Node']}.{row['End_Node_Phase']} "
                f"phases={row['Phases']} "
                f"length={row['Length']} units={row['Units']} "
                f"linecode=lc_{row['Linecode']}-{row['Phases']}ph "
                f"enabled=true"
            )
            self.commands["04_MV_Lines.dss"].append(cmd)

    def capacitors_optional(self):
        if "mvcaps" not in self.data:
            return
        element = self.data["mvcaps"]
        for _, row in element.iterrows():
            cmd = (
                f"New Capacitor.mv_f0_l{row['Element_ID']} "
                f"bus1=mv_f0_n{row['Bus1']}.1.2.3 "
                f"phases={row['phases']} kvar={row['kvar']} kV={row['kvs']}"
            )
            self.commands["05_Capacitors.dss"].append(cmd)

    def regulators_optional(self):
        if "mvtx" not in self.data:
            return

        element = self.data["mvtx"]
        c2n = char_to_num_map()

        # only keep ones that behave as regulators (kvs_primary == kvs_secondary)
        for _, row in element.iterrows():
            kva1 = row["kvs_primary"]
            kva2 = row["kvs_secondary"]

            if kva1 != kva2:
                # your code: non-reg transformer definition
                cmd = (
                    f"New Transformer.{row['Substation_ID']} "
                    f"buses=[mv_f0_n{row['Bus1']}.{c2n[row['Conn_Type']]} mv_f0_n{row['Bus2']}.1.0 mv_f0_n{row['Bus2']}.0.2] "
                    f"phases=1 windings=3 conns=[Delta Wye Wye] "
                    f"kVs=[{row['kvs_primary']} {row['kvs_secondary']} {row['kvs_secondary']}] "
                    f"kVAs=[{row['kvas_primary']} {row['kvas_secondary']} {row['kvas_secondary']}] "
                    f"xhl={row['xhl']} %noloadloss={row['noloadloss']} %loadloss={row['loadloss']}"
                )
                self.commands["06_Regulators.dss"].append(cmd)
                continue

            # regulator case
            self.commands["06_Regulators.dss"].append("Set MaxControlIter=100")
            # total 3-phase kVA for this regulator (used by mv_build to set sn_mva)
            self.commands["06_Regulators.dss"].append(
                f"! regulator_kva={row['Substation_ID']} {row['kvas_primary']}"
            )

            # reactors jumpers
            sid = row["Substation_ID"]
            b1 = row["Bus1"]
            b2 = row["Bus2"]

            self.commands["06_Regulators.dss"] += [
                f"New Reactor.Jumper_{sid}_A_E phases=1 bus1=mv_f0_n{b1}.1 bus2=Jumper_{sid}_A.2 X=0.0001 R=0.0001",
                f"New Reactor.Jumper_{sid}_A_O phases=1 bus1=Jumper_{sid}_A.1 bus2=mv_f0_n{b2}.1 X=0.0001 R=0.0001",
                f"New Reactor.Jumper_{sid}_B_E phases=1 bus1=mv_f0_n{b1}.2 bus2=Jumper_{sid}_B.2 X=0.0001 R=0.0001",
                f"New Reactor.Jumper_{sid}_B_O phases=1 bus1=Jumper_{sid}_B.1 bus2=mv_f0_n{b2}.2 X=0.0001 R=0.0001",
                f"New Reactor.Jumper_{sid}_C_E phases=1 bus1=mv_f0_n{b1}.3 bus2=Jumper_{sid}_C.2 X=0.0001 R=0.0001",
                f"New Reactor.Jumper_{sid}_C_O phases=1 bus1=Jumper_{sid}_C.1 bus2=mv_f0_n{b2}.3 X=0.0001 R=0.0001",
            ]

            # transformer per phase + regcontrol
            kv = 12.7
            nt = 10 / 100
            kVAtraf = str(np.round((nt * float(kva1) / (1 + nt)), 2))

            for ph in ["A", "B", "C"]:
                self.commands["06_Regulators.dss"].append(
                    f"New Transformer.{sid}_{ph} phases=1 windings=2 "
                    f"xhl={row['xhl']} %noloadloss={row['noloadloss']} %loadloss={row['loadloss']} "
                    f"wdg=1 Bus=Jumper_{sid}_{ph}.1.0 kV={kv} kVA={kVAtraf} "
                    f"wdg=2 Bus=Jumper_{sid}_{ph}.1.2 kV={kv/10} kVA={kVAtraf} "
                    f"Maxtap=1.0 Mintap=-1.0 tap=0.0 numtaps={row['wdg1_numtaps']-1}"
                )
                self.commands["06_Regulators.dss"].append(
                    f"New Regcontrol.Reg_{sid}_{ph} transformer={sid}_{ph} winding=2 "
                    f"bus=Jumper_{sid}_{ph}.1 vreg=100.0 band=3.0 ptratio={kv*10} maxtapchange=1"
                )

    def lv_tx(self):
        element = self.data["lvtx"]
        c2n = char_to_num_map()

        for idx, row in element.iterrows():
            if len(row["Conn_Type"]) == 3:
                cmd = (
                    f"New Transformer.mv_f0_lv_{row['Substation_ID']} "
                    f"phases=3 windings=2 "
                    f"buses=[mv_f0_n{row['Bus1']} mv_f0_lv{idx}_busbar] "
                    f"conns=[{row['Connection_Primary']} {row['Connection_Secondary']}] "
                    f"kVs=[{row['kvs_primary']} {row['kvs_secondary']}] "
                    f"kVAs=[{row['kvas_primary']} {row['kvas_secondary']}] "
                    f"xhl={row['xhl']} %noloadloss={row['noloadloss']} %loadloss={row['loadloss']} "
                    f"wdg=1 numtaps=4 tap={row['wdg1_tap']} maxtap=1.137 mintap=1.028"
                )
            elif len(row["Conn_Type"]) == 2:
                cmd = (
                    f"New Transformer.mv_f0_lv_{row['Substation_ID']} "
                    f"phases=1 windings=3 "
                    f"buses=[mv_f0_n{row['Bus1']}.{c2n[row['Conn_Type']]} mv_f0_lv{idx}_busbar.1.0 mv_f0_lv{idx}_busbar.0.2] "
                    f"conns=[Delta Wye Wye] "
                    f"kVs=[22 0.25 0.25] "
                    f"kVAs=[{row['kvas_primary']} {row['kvas_secondary']} {row['kvas_secondary']}] "
                    f"xhl={row['xhl']} %noloadloss={row['noloadloss']} %loadloss={row['loadloss']} "
                    f"wdg=1 numtaps=4 tap={row['wdg1_tap']} maxtap=1.137 mintap=1.028"
                )
            else:
                cmd = (
                    f"New Transformer.mv_f0_lv_{row['Substation_ID']} "
                    f"phases=1 windings=2 "
                    f"buses=[mv_f0_n{row['Bus1']}.{c2n[row['Conn_Type']]} mv_f0_lv{idx}_busbar.1] "
                    f"conns=[Wye Wye] "
                    f"kVs=[{row['kvs_primary']} {row['kvs_secondary']}] "
                    f"kVAs=[{row['kvas_primary']} {row['kvas_secondary']}] "
                    f"xhl={row['xhl']} %noloadloss={row['noloadloss']} %loadloss={row['loadloss']} "
                    f"wdg=1 numtaps=4 tap={row['wdg1_tap']} maxtap=1.137 mintap=1.028"
                )

            self.commands["07_LV_Tx.dss"].append(cmd)

    def lv_lines(self):
        element = self.data["lv_lines"]
        for _, row in element.iterrows():
            bus_conn = ".1.2.3" if int(row["phases"]) == 3 else ".1"
            cmd = (
                f"New Line.{row['line_name']} "
                f"bus1={row['bus1']}{bus_conn} "
                f"bus2={row['bus2']}{bus_conn} "
                f"phases={row['phases']} length={row['length']} units={row['units']} "
                f"linecode={row['linecode']}"
            )
            self.commands["08_LV_Lines.dss"].append(cmd)

    def loadshapes_and_loads(self, selected_day: int, seed: int):
        np.random.seed(seed)
        profile_map: dict = {}

        # Load profile arrays
        house_data = np.load(str(config.RES_PROFILE_NPY))
        com_data   = np.load(str(config.COM_PROFILE_NPY))

        npts = int((24 * 60) / TIME_RES_MIN)

        loads = self.data["lv_loads"]
        lvtx = self.data["lvtx"]

        for idx, row in loads.iterrows():
            is_res = int(row["phases"]) == 1
            load_name = row["load_name"]

            if is_res:
                # pick random house profile
                pidx = np.random.randint(len(house_data))
                prof = house_data[pidx, selected_day - 1, :]
                shape_name = f"Load_shape_res_{idx}"
                profile_map[shape_name] = {"type": "res", "profile_idx": int(pidx)}

                # export CSV (48 lines)
                csv_name = f"{shape_name}.csv"
                csv_path = os.path.join(self.profiles_dir, csv_name)
                np.savetxt(csv_path, prof.reshape(-1), fmt="%.8f")

                # DSS Loadshape using file
                self.commands["09_LoadShapes.dss"].append(
                    f"New Loadshape.{shape_name} npts={npts} minterval={TIME_RES_MIN} mult=(file={PROFILES_DIR}/{csv_name}) useactual=no"
                )

                # DSS Load referencing daily=
                self.commands["10_Loads.dss"].append(
                    f"New Load.{load_name} phases={row['phases']} bus1={row['bus1']} "
                    f"kw=1 conn=wye kv={row['kv']} pf={row['pf']} model=1 "
                    f"vminpu=0.0 vmaxpu=2 status={row['model']} daily={shape_name} enabled=true"
                )

            else:
                # choose a com profile that satisfies load_max < tx_cap/2
                # (όπως στον κώδικα σου)
                tx_cap = row.get("tx_cap", None)
                while True:
                    pidx = np.random.randint(len(com_data))
                    prof = com_data[pidx, selected_day - 1, :]
                    if tx_cap is None or (np.max(prof) < tx_cap / 2):
                        break

                shape_name = f"Load_shape_com_{idx}"
                profile_map[shape_name] = {"type": "com", "profile_idx": int(pidx)}
                csv_name = f"{shape_name}.csv"
                csv_path = os.path.join(self.profiles_dir, csv_name)
                np.savetxt(csv_path, prof.reshape(-1), fmt="%.8f")

                self.commands["09_LoadShapes.dss"].append(
                    f"New Loadshape.{shape_name} npts={npts} minterval={TIME_RES_MIN} mult=(file={PROFILES_DIR}/{csv_name}) useactual=no"
                )

                self.commands["10_Loads.dss"].append(
                    f"New Load.{load_name} phases={row['phases']} bus1={row['bus1']} "
                    f"kw=1 conn=wye kv={row['kv']} pf={row['pf']} model=1 "
                    f"vminpu=0.0 vmaxpu=2 status={row['model']} daily={shape_name} enabled=true"
                )

        # Save profile index map so run_power_flow can use any day from the .npy arrays
        import json as _json
        map_path = os.path.join(self.profiles_dir, "profile_map.json")
        with open(map_path, "w", encoding="utf-8") as _f:
            _json.dump(profile_map, _f)
        print(f"[INFO] profile_map.json saved ({len(profile_map)} entries)")

    def other_commands_master(self, note: str = ""):
        # αν θες metadata/σχόλια μέσα σε ένα file
        self.commands["01_Circuit.dss"].insert(0, f"! {note}")


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    #check_data()

    from pathlib import Path as _P
    _sentinel = _P(EXPORT_DIR) / ".profiles_day.txt"
    if _sentinel.exists() and _sentinel.read_text().strip() == str(SELECTED_DAY):
        print(f"[CACHE] Profiles already generated for day {SELECTED_DAY} — skipping.")
        sys.exit(0)

    xlsx_name = identify_network_xlsx(NETWORK_OPTION)
    xlsx_path = str(config.EXCELS_DIR / xlsx_name)
    print(f"Using network file: {xlsx_path}")
    nd = NetworkData(xlsx_path)
    exporter = DSSExporter(nd.data, EXPORT_DIR)
    exporter.export_all(selected_day=SELECTED_DAY, seed=SEED)
    _sentinel.write_text(str(SELECTED_DAY))
