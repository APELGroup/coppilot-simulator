"""
nando_runs/nando_run_balanced.py

Balanced (1-phase equivalent) OpenDSS daily timeseries run.
Builds the full network from the Excel input file, solves 48 x 30-min steps,
and writes three output CSVs:

  1. excels/Vdata_all_buses_clean.csv      – per-node voltages [V], filtered
  2. excels/all_lines_loading_percent.csv  – all line loading [%]
  3. excels/Vmean_vm_pu_with_source.csv    – mean voltage per bus in p.u.

Configuration (network selection, paths, selected day) is read from config.py.
"""

import sys
import os
import glob
from pathlib import Path
import re
from datetime import datetime, timedelta
from itertools import permutations

import numpy as np
import pandas as pd
import warnings

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D

import geopandas as gp
from shapely.geometry import Point, LineString

from tqdm import tqdm
from tabulate import tabulate
from colorama import Fore, Style

try:
    import dss as dss_direct
    print(f"Your Python environment has 'dss_python: {dss_direct.__version__}'.", file=sys.stderr)
    if dss_direct.__version__ != "0.12.1":
        print(
            f"The dss_python version installed is different from what was used to develop this code "
            f"(dss_python version 0.12.1). If you have troubles related to OpenDSS, please re-install "
            f"dss_python version 0.12.1."
        )
except ModuleNotFoundError:
    raise ModuleNotFoundError(
        "Module 'dss_python' not found.\n"
        '  → Please install via command "pip install dss_python" in terminal.'
    )

# ── config ────────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

np.random.seed(config.SEED)


# ══════════════════════════════════════════════════════════════════════════════
# Classes
# ══════════════════════════════════════════════════════════════════════════════

class WrongNetworkNameError(Exception):
    pass


class MissingExcelSheetsError(Exception):
    pass


class NetworkData:
    """Load and tabulate network data from an Excel file."""

    def __init__(self, name, data_location):
        options = ["1", "2", "3", "4"]
        net_names = ["Rural_1", "Rural_2", "Urban_1", "Urban_2"]

        self.network_name: str = net_names[options.index(name.upper())]
        self.data_location: str = data_location
        self.data: dict = {}
        self.get_network_data()
        self.tabulate_data()

    def get_network_data(self):
        sheets = self.get_excel_sheet_names()
        for sheet_name in tqdm(sheets, desc="Extracting data: ", unit="sheet"):
            self.data[sheet_name] = pd.read_excel(self.data_location, sheet_name=sheet_name)
        return self.data

    def get_excel_sheet_names(self):
        try:
            xl = pd.ExcelFile(self.data_location)
            return xl.sheet_names
        except FileNotFoundError:
            print("File not found or incorrect path.")
            return None

    def tabulate_data(self):
        n_res_txs = self.data['lvtx']["Type"].value_counts().get('RES', 0)
        n_res_cus = self.data['lv_loads']["phases"].value_counts().get(1, 0)
        n_com_txs = self.data['lvtx']["Type"].value_counts().get('COM', 0)
        n_com_cus = self.data['lv_loads']["phases"].value_counts().get(3, 0)
        try:
            n_mvmv_txs = (~self.data['mvtx']["Substation_ID"].str.contains('_REG')).sum()
        except Exception:
            n_mvmv_txs = 0
        try:
            n_reg_txs = self.data['mvtx']["Substation_ID"].str.contains('_REG').sum()
        except Exception:
            n_reg_txs = 0
        try:
            n_caps = self.data['mvcaps']["phases"].value_counts().get(3, 0)
        except Exception:
            n_caps = 0
        n_swer_txs = len(self.data['lvtx'][self.data['lvtx']["Conn_Type"].astype(str).str.len() != 3])
        len_mv_lines = self.data["lines"]["Length"].sum()
        len_mv_swer_lines = self.data["lines"].loc[self.data["lines"]["Phases"] == 1]["Length"].sum()
        len_lv_lines = self.data["lv_lines"]["length"].sum()
        len_lv_swer_lines = self.data["lv_lines"].loc[self.data["lv_lines"]["phases"] == 1]["length"].sum()

        data_tuples = [
            ('# of LV Residential Substations', n_res_txs),
            ('# of LV Residential Customers', n_res_cus),
            ('# of LV Non-Residential Substations', n_com_txs),
            ('# of LV Non-Residential Customers', n_com_cus),
            ('# of SWER MV Transformers', n_mvmv_txs),
            ('# of Voltage Regulators', n_reg_txs),
            ('# of MV Capacitors', n_caps),
            ('# of SWER LV Transformers', n_swer_txs),
            ('MV conductor length', f"{np.round(len_mv_lines, 2)} km"),
            ('MV SWER conductor length', f"{np.round(len_mv_swer_lines, 2)} km"),
            ('LV conductor length', f"{np.round(len_lv_lines / 1000, 2)} km"),
            ('LV SWER conductor length', f"{np.round(len_lv_swer_lines / 1000, 2)} km"),
        ]
        filtered_data = [item for item in data_tuples if item[1] != 0 and item[1] != '0.0 km' and item[1] != '0.00 km']
        print("\033[1;92mNetwork Data\033[0m")
        print(tabulate(filtered_data, headers=['Parameter', 'Quantity'], tablefmt="github"))

    def network_plotting(self):
        """Build GeoDataFrames and plot the network topology."""
        desired_crs = 'EPSG:4462'

        mvbuses_layer = self.data["buscoords"]
        geometry = [Point(xy) for xy in zip(mvbuses_layer['NodeStartX'], mvbuses_layer['NodeStartY'])]
        mvbuses_layer_gp = gp.GeoDataFrame(mvbuses_layer, geometry=geometry, crs=desired_crs)
        mvbuses_layer_gp = mvbuses_layer_gp.set_geometry('geometry')
        mvbuses_layer_gp.index = mvbuses_layer_gp["Node_ID"]

        mvtx_layer = self.data["mv_net_txs"]
        mvtx_geometries = [
            mvbuses_layer_gp.loc[row['Bus2'], 'geometry']
            for _, row in mvtx_layer.iterrows()
        ]
        self.mvtxs_layer_gp = gp.GeoDataFrame(mvtx_layer, geometry=mvtx_geometries, crs=desired_crs)

        mvlines_layer = self.data["lines"].loc[self.data["lines"]["Element_Name"].str.lower() != "delete"]
        line_geometries = [
            LineString([
                mvbuses_layer_gp.loc[row['Start_Node'], 'geometry'],
                mvbuses_layer_gp.loc[row['End_Node'], 'geometry']
            ])
            for _, row in mvlines_layer.iterrows()
        ]
        self.mvlines_layer_gp = gp.GeoDataFrame(mvlines_layer, geometry=line_geometries, crs=desired_crs)

        txs_layer = self.data['lvtx']
        tx_geometries = [
            mvbuses_layer_gp.loc[row['Bus1'], 'geometry']
            for _, row in txs_layer.iterrows()
        ]
        self.txs_layer_gp = gp.GeoDataFrame(txs_layer, geometry=tx_geometries, crs=desired_crs)

        cap_flag = False
        try:
            caps_layer = self.data['mvcaps']
            caps_geometries = [
                mvbuses_layer_gp.loc[row['Bus1'], 'geometry']
                for _, row in caps_layer.iterrows()
            ]
            self.caps_layer_gp = gp.GeoDataFrame(caps_layer, geometry=caps_geometries, crs=desired_crs)
            cap_flag = True
        except Exception:
            pass

        network_gp = {
            "MV_tx": self.mvtxs_layer_gp,
            "MV_lines": self.mvlines_layer_gp,
            "MVLV_txs": self.txs_layer_gp,
        }
        if cap_flag:
            network_gp["caps"] = self.caps_layer_gp

        # --- Plot ---
        is_urban = "urban" in self.network_name.lower()
        fig, ax = plt.subplots(figsize=(7, 5), dpi=150 if is_urban else 100)
        self.mvtxs_layer_gp.plot(ax=ax, color="black", alpha=0.7, marker="^", markersize=264, zorder=1)
        self.mvlines_layer_gp.plot(ax=ax, color="grey", alpha=0.7, linewidth=2.5, zorder=2)
        if is_urban:
            self.txs_layer_gp.loc[self.txs_layer_gp["Type"] == "COM"].plot(ax=ax, color="blue", marker="o", markersize=64, zorder=3)
            self.txs_layer_gp.loc[self.txs_layer_gp["Type"] == "RES"].plot(ax=ax, color="black", marker="o", markersize=64, zorder=3)
        else:
            self.txs_layer_gp.loc[(self.txs_layer_gp["Type"] == "COM") & (self.txs_layer_gp["Conn_Type"].str.len() == 3)].plot(ax=ax, color="blue", marker="o", markersize=32, zorder=3)
            self.txs_layer_gp.loc[(self.txs_layer_gp["Type"] == "RES") & (self.txs_layer_gp["Conn_Type"].str.len() == 3)].plot(ax=ax, color="black", marker="o", markersize=32, zorder=3)
            self.txs_layer_gp.loc[(self.txs_layer_gp["Type"] == "RES") & (self.txs_layer_gp["Conn_Type"].str.len() != 3)].plot(ax=ax, color="sandybrown", marker="o", markersize=32, zorder=3)
        if cap_flag:
            self.caps_layer_gp.plot(ax=ax, color="darkslateblue", marker="s", markersize=64, zorder=3)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title("Network Topology", fontsize=10)
        plt.tight_layout()
        plt.show()

        return network_gp


class DSSDriver:
    """Interface to the OpenDSS engine for network building and simulation."""

    def __init__(self, data, gis_data):
        self.data = data
        self.gis_data = gis_data

        self.dss = dss_direct.DSS
        self.dss.Start(0)
        self.dss_text = self.dss.Text
        self.dss_circuit = self.dss.ActiveCircuit
        self.dss_solution = self.dss.ActiveCircuit.Solution
        self.ready = False

    @staticmethod
    def get_date_and_season(day_of_year):
        start_of_year = datetime(year=datetime.now().year, month=1, day=1)
        date = start_of_year + timedelta(days=day_of_year - 1)
        date_str = date.strftime("%B %d")
        if 355 <= day_of_year or day_of_year <= 78:
            season = "Summer"
        elif 79 <= day_of_year <= 170:
            season = "Autumn"
        elif 171 <= day_of_year <= 263:
            season = "Winter"
        else:
            season = "Spring"
        return date_str, season

    def basic_opendss_actions(self):
        self.dss_text.Command = 'clear'
        self.dss_text.Command = 'Set DefaultBaseFrequency = 50'

    def voltage_source(self):
        self.dss_text.Command = "New circuit.circuit basekv=66 pu=1 angle=0 phases=3 R1=0.52824 X1=2.113 R0=0.59157 X0=1.7747"
        self.dss_text.Command = "edit vsource.source bus1=sourcebus basekv=66 pu=1 angle=0 phases=3 R1=0.52824 X1=2.113 R0=0.59157 X0=1.7"

    def mv_net_tx(self):
        element = self.data["mv_net_txs"]
        for index, row in tqdm(element.iterrows(), desc="Building the circuit - MV Transformers  : ", total=len(element)):
            self.dss_text.Command = (
                f"New Transformer.{row['Substation_ID']} "
                f"phases=3 windings=2 "
                f"buses=[{row['Bus1']}, mv_f0_n{row['Bus2']}] "
                f"conns=[{row['Connection_Primary']}, {row['Connection_Secondary']}] "
                f"kVs=[{row['kvs_primary']}, {row['kvs_secondary']}] "
                f"kVAs=[{row['kvas_primary']}, {row['kvas_secondary']}] "
                f"%loadloss={row['loadloss']} %noloadloss={row['noloadloss']} "
                f"xhl={row['xhl']} enabled=true"
            )

    def line_codes(self):
        element = self.data["linecodes"]
        for index, row in tqdm(element.iterrows(), desc="Building the circuit - Linecodes        : ", total=len(element)):
            self.dss_text.Command = (
                f"new linecode.lc_{row['Linecode_ID']} "
                f"nphases={row['Phases']} "
                f"r1={row['r1']} x1={row['x1']} b1={row['b1']} "
                f"r0={row['r0']} b0={row['b0']} x0={row['x0']} "
                f"units={row['Units']} "
                f"normamp={min(row['Ampacity1'], row['Ampacity2'])}"
            )

    def connections(self):
        element = self.data["lines"]
        for index, row in tqdm(element.iterrows(), desc="Building the circuit - MV Lines         : ", total=len(element)):
            if row["Element_Name"].lower() != "delete":
                self.dss_text.Command = (
                    f"new line.mv_f0_l{row['Line_Number']} "
                    f"bus1=mv_f0_n{row['Start_Node']}.{row['Start_Node_Phase']} "
                    f"bus2=mv_f0_n{row['End_Node']}.{row['End_Node_Phase']} "
                    f"phases={row['Phases']} length={row['Length']} units={row['Units']} "
                    f"linecode=lc_{row['Linecode']}-{row['Phases']}ph enabled=true"
                )
                self.gis_data["MV_lines"].loc[index, "DSSNAME"] = f"mv_f0_l{row['Line_Number']}"
                amp = self.data["linecodes"].loc[
                    self.data["linecodes"]["Linecode_ID"] == f"{row['Linecode']}-{row['Phases']}ph",
                    "Ampacity1"
                ].values[0]
                self.gis_data["MV_lines"].loc[index, "Ampacity"] = amp

    def capacitors(self):
        element = self.data["mvcaps"]
        for index, row in tqdm(element.iterrows(), desc="Building the circuit - MV Capacitors    : ", total=len(element)):
            self.dss_text.Command = (
                f"new capacitor.mv_f0_l{row['Element_ID']} "
                f"bus1=mv_f0_n{row['Bus1']}.1.2.3 "
                f"phases={row['phases']} kvar={row['kvar']} kV={row['kvs']}"
            )

    def mv_txs(self):
        three_ph_combi = [''.join(perm) for perm in list(permutations(['R', 'W', 'B']))]
        two_ph_combi = [''.join(perm) for perm in list(permutations(['R', 'B', 'W'], 2))]
        one_ph_combi = [''.join(perm) for perm in list(permutations(['R', 'B', 'W'], 1))]
        char_to_num = {
            key: '.'.join(str({'R': 1, 'W': 2, 'B': 3}[char]) for char in key)
            for key in three_ph_combi + two_ph_combi + one_ph_combi
        }

        element = self.data["mvtx"]
        for index, row in element.iterrows():
            kva1 = row["kvs_primary"]
            kva2 = row["kvs_secondary"]

            if kva1 != kva2:
                self.dss_text.Command = (
                    f"new transformer.{row['Substation_ID']} "
                    f"buses=[mv_f0_n{row['Bus1']}.{char_to_num[row['Conn_Type']]} "
                    f"mv_f0_n{row['Bus2']}.1.0 mv_f0_n{row['Bus2']}.0.2] "
                    f"phases=1 windings=3 conns=[Delta Wye Wye] "
                    f"kVs=[{row['kvs_primary']} {row['kvs_secondary']} {row['kvs_secondary']}] "
                    f"kVAs=[{row['kvas_primary']} {row['kvas_secondary']} {row['kvas_secondary']}] "
                    f"xhl={row['xhl']} %noloadloss={row['noloadloss']} %loadloss={row['loadloss']}"
                )
            else:
                # Autotransformer regulator
                self.dss_text.Command = "set maxcontroliter=100"
                for phase, ph_num in [("A", 1), ("B", 2), ("C", 3)]:
                    self.dss_text.Command = (
                        f"New Reactor.Jumper_{row['Substation_ID']}_{phase}_E phases=1 "
                        f"bus1=mv_f0_n{row['Bus1']}.{ph_num} "
                        f"bus2=Jumper_{row['Substation_ID']}_{phase}.2 X=0.0001 R=0.0001"
                    )
                    self.dss_text.Command = (
                        f"New Reactor.Jumper_{row['Substation_ID']}_{phase}_O phases=1 "
                        f"bus1=Jumper_{row['Substation_ID']}_{phase}.1 "
                        f"bus2=mv_f0_n{row['Bus2']}.{ph_num} X=0.0001 R=0.0001"
                    )

                kv = 12.7
                nt = 10 / 100
                kVAtraf = str(np.round((nt * float(kva1) / (1 + nt)), 2))

                for phase in ["A", "B", "C"]:
                    self.dss_text.Command = (
                        f"new transformer.{row['Substation_ID']}_{phase} "
                        f"phases=1 windings=2 "
                        f"xhl={row['xhl']} %noloadloss={row['noloadloss']} %loadloss={row['loadloss']} "
                        f"wdg=1 Bus=Jumper_{row['Substation_ID']}_{phase}.1.0 kV={kv} kVA={kVAtraf} "
                        f"wdg=2 Bus=Jumper_{row['Substation_ID']}_{phase}.1.2 kV={kv / 10} kVA={kVAtraf} "
                        f"Maxtap=1.0 Mintap=-1.0 tap=0.0 numtaps={row['wdg1_numtaps'] - 1}"
                    )
                for phase in ["A", "B", "C"]:
                    self.dss_text.Command = (
                        f" new regcontrol.Reg_{row['Substation_ID']}_{phase} "
                        f"transformer={row['Substation_ID']}_{phase} winding=2 "
                        f"bus=Jumper_{row['Substation_ID']}_{phase}.1 "
                        f"vreg=100.0 band=3.0 ptratio={kv * 10} maxtapchange=1"
                    )
        return

    def lv_tx(self):
        three_ph_combi = [''.join(perm) for perm in list(permutations(['R', 'W', 'B']))]
        two_ph_combi = [''.join(perm) for perm in list(permutations(['R', 'B', 'W'], 2))]
        one_ph_combi = [''.join(perm) for perm in list(permutations(['R', 'B', 'W'], 1))]
        char_to_num = {
            key: '.'.join(str({'R': 1, 'W': 2, 'B': 3}[char]) for char in key)
            for key in three_ph_combi + two_ph_combi + one_ph_combi
        }

        element = self.data["lvtx"]
        for index, row in tqdm(element.iterrows(), desc="Building the circuit - LV Transformers  : ", total=len(element)):
            if len(row['Conn_Type']) == 3:
                lv_tx_data = (
                    f"new transformer.mv_f0_lv_{row['Substation_ID']} "
                    f"phases=3 windings=2 "
                    f"buses=[mv_f0_n{row['Bus1']} mv_f0_lv{index}_busbar] "
                    f"conns=[{row['Connection_Primary']} {row['Connection_Secondary']}] "
                    f"kVs=[{row['kvs_primary']} {row['kvs_secondary']}] "
                    f"kVAs=[{row['kvas_primary']} {row['kvas_secondary']}] "
                    f"xhl={row['xhl']} %noloadloss={row['noloadloss']} %loadloss={row['loadloss']} "
                    f"wdg=1 numtaps=4 tap={row['wdg1_tap']} maxtap=1.137 mintap=1.028"
                )
            elif len(row['Conn_Type']) == 2:
                lv_tx_data = (
                    f"new transformer.mv_f0_lv_{row['Substation_ID']} "
                    f"phases=1 windings=3 "
                    f"buses=[mv_f0_n{row['Bus1']}.{char_to_num[row['Conn_Type']]} "
                    f"mv_f0_lv{index}_busbar.1.0 mv_f0_lv{index}_busbar.0.2] "
                    f"conns=[Delta Wye Wye] kVs=[22 0.25 0.25] "
                    f"kVAs=[{row['kvas_primary']} {row['kvas_secondary']} {row['kvas_secondary']}] "
                    f"xhl={row['xhl']} %noloadloss={row['noloadloss']} %loadloss={row['loadloss']} "
                    f"wdg=1 numtaps=4 tap={row['wdg1_tap']} maxtap=1.137 mintap=1.028"
                )
            else:
                lv_tx_data = (
                    f"new transformer.mv_f0_lv_{row['Substation_ID']} "
                    f"phases=1 windings=2 "
                    f"buses=[mv_f0_n{row['Bus1']}.{char_to_num[row['Conn_Type']]} mv_f0_lv{index}_busbar.1] "
                    f"conns=[Wye Wye] "
                    f"kVs=[{row['kvs_primary']} {row['kvs_secondary']}] "
                    f"kVAs=[{row['kvas_primary']} {row['kvas_secondary']}] "
                    f"xhl={row['xhl']} %noloadloss={row['noloadloss']} %loadloss={row['loadloss']} "
                    f"wdg=1 numtaps=4 tap={row['wdg1_tap']} maxtap=1.137 mintap=1.028"
                )
            self.dss_text.Command = lv_tx_data
            self.gis_data["MVLV_txs"].loc[index, "DSSNAME"] = f"mv_f0_lv_{row['Substation_ID']}"

    def lv_nets(self):
        element = self.data["lv_lines"]
        for index, row in tqdm(element.iterrows(), desc="Building the circuit - LV Lines         : ", total=len(element)):
            bus_conn = ".1.2.3" if row['phases'] == 3 else ".1"
            self.dss_text.Command = (
                f"new line.{row['line_name']} "
                f"bus1={row['bus1']}{bus_conn} bus2={row['bus2']}{bus_conn} "
                f"phases={row['phases']} length={row['length']} "
                f"units={row['units']} linecode={row['linecode']}"
            )

    def lv_load_mod(self, selected_day=0):
        # Use config paths for profile data
        house_data = np.load(str(config.RES_PROFILE_NPY))
        com_data = np.load(str(config.COM_PROFILE_NPY))
        time_res = config.TIME_RES_MIN

        if selected_day == 0:
            np.random.seed(config.SEED)
            selected_day = int(np.random.randint(0, 365))

        element = self.data["lv_loads"]
        for index, row in tqdm(element.iterrows(), desc="Building the circuit - Customer loadings: ", total=len(element)):
            load_data = (
                f"new load.{row['load_name']} "
                f"phases={row['phases']} bus1={row['bus1']} kw=1 conn=wye "
                f"kv={row['kv']} pf={row['pf']} model=1 "
                f"vminpu=0.0 vmaxpu=2 status={row['model']} enabled=True"
            )
            self.dss_text.Command = load_data

            if row['phases'] == 1:
                profile = house_data[np.random.randint(len(house_data)), selected_day, :]
                shape_name = f"Load_shape_res_{index}"
            else:
                while True:
                    profile = com_data[np.random.randint(len(com_data)), selected_day, :]
                    if np.max(profile) < row['tx_cap'] / 2:
                        break
                shape_name = f"Load_shape_com_{index}"

            self.dss_text.Command = (
                f"New Loadshape.{shape_name} "
                f"npts={int((24 * 60) / time_res)} minterval={time_res} "
                f"Pmult={profile.tolist()} useactual=no"
            )
            self.dss_circuit.SetActiveElement(f"load.{row['load_name']}")
            self.dss_circuit.ActiveElement.Properties('daily').Val = shape_name

        return selected_day

    def print_selected_date(self, selected_day):
        date_str, season = DSSDriver.get_date_and_season(selected_day)
        print(f"Selected day: {date_str} ({season} season).")

    def other_opendss_commands(self):
        self.dss_text.Command = 'Set VoltageBases=[66.0, 22.0, 12.7 0.400, 0.2309]'
        self.dss_text.Command = 'calcv'


# ══════════════════════════════════════════════════════════════════════════════
# Simulation functions
# ══════════════════════════════════════════════════════════════════════════════

def run_daily(driver: DSSDriver):
    """
    Solve 48 x 30-min steps (daily mode) and collect voltage and current data.

    Returns
    -------
    Vdata : pd.DataFrame  – voltages [V] for all phase nodes (rows=timestep, cols=node.phase)
    Idata : pd.DataFrame  – average phase current [A] for all lines (rows=timestep, cols=line_name)
    Sdata_txs : pd.DataFrame – apparent power [kVA] per LV transformer (rows=timestep)
    """
    driver.dss_text.Command = 'Set Mode=daily number=1 stepsize=30m'
    driver.dss_text.Command = 'Set time=(0,0)'

    # All phase nodes in the circuit (.1 .2 .3 only, no neutrals)
    all_node_names = [str(x).strip() for x in driver.dss_circuit.AllNodeNames]
    all_voltage_nodes = list(dict.fromkeys([
        node for node in all_node_names
        if len(node.split(".")) >= 2 and node.split(".")[1] in {"1", "2", "3"}
    ]))

    # LV transformer names
    txs_name = [x for x in driver.dss_circuit.Transformers.AllNames if "mv_f0_lv_" in x]

    # Allocate output DataFrames
    import os as _os
    _npts = int(_os.environ.get("NANDO_VALIDATION_STEPS", "48"))
    Vdata = pd.DataFrame(index=range(_npts), columns=all_voltage_nodes)
    Idata = pd.DataFrame(
        index=range(_npts),
        columns=[driver.gis_data["MV_lines"].loc[x, "DSSNAME"] for x in driver.gis_data["MV_lines"].index]
    )
    sdata_txs_list = []

    for it in tqdm(range(_npts), desc=f"Solving balanced timeseries ({_npts} steps)"):
        driver.dss_solution.Solve()

        # Voltages – all phase nodes
        all_V = pd.DataFrame(
            list(driver.dss_circuit.AllBusVmag),
            index=list(driver.dss_circuit.AllNodeNames),
            columns=['Val']
        )
        Vdata.loc[it, :] = all_V.loc[all_voltage_nodes, "Val"].values

        # LV transformer apparent powers
        tx_dict = {}
        for tx in txs_name:
            driver.dss_circuit.Transformers.Name = tx
            powers = driver.dss_circuit.ActiveElement.Powers
            phases = driver.dss_circuit.ActiveElement.Properties("phases").Val
            if phases == "1":
                p = float(powers[0])
                q = float(powers[1])
            else:
                p = float(powers[0]) + float(powers[2]) + float(powers[4])
                q = float(powers[1]) + float(powers[3]) + float(powers[5])
            tx_dict[tx] = np.sqrt(p ** 2 + q ** 2)
        sdata_txs_list.append(pd.Series(tx_dict, name=it))

        # MV line currents
        for idx in driver.gis_data["MV_lines"].index:
            line_name = driver.gis_data["MV_lines"].loc[idx, "DSSNAME"].lower()
            driver.dss_circuit.Lines.Name = line_name
            phases_str = driver.dss_circuit.ActiveElement.Properties("phases").Val
            currents = driver.dss_circuit.ActiveElement.CurrentsMagAng
            if phases_str == "1":
                av_current = float(currents[0])
            else:
                av_current = (float(currents[0]) + float(currents[2]) + float(currents[4])) / 3
            Idata.loc[it, line_name] = av_current

    Sdata_txs = pd.concat(sdata_txs_list, axis=1).T

    # Store daily max on GIS layers
    for idx in driver.gis_data["MVLV_txs"].index:
        tx = driver.gis_data["MVLV_txs"].loc[idx, "DSSNAME"].lower()
        driver.gis_data["MVLV_txs"].loc[idx, "DAILY_max"] = Sdata_txs.loc[:, tx].max()
    for idx in driver.gis_data["MV_lines"].index:
        line = driver.gis_data["MV_lines"].loc[idx, "DSSNAME"].lower()
        driver.gis_data["MV_lines"].loc[idx, "DAILY_max"] = Idata.loc[:, line].max()

    return Vdata, Idata, Sdata_txs


def export_all_line_loading_csv(
    out_csv: str,
    npts: int = 48,
    stepsize_minutes: int = 30,
) -> pd.DataFrame:
    """
    Compute line loading [%] for ALL OpenDSS lines (MV + LV) by compiling
    Master.dss directly and running a balanced daily solve.

    Uses max(phase_A, phase_B, phase_C) current as the 1-phase equivalent –
    in a balanced system all phases are equal; in a lightly unbalanced system
    the max is the conservative value.
    """
    _dss = dss_direct.DSS
    _dss.Start(0)
    _text    = _dss.Text
    _circuit = _dss.ActiveCircuit
    _sol     = _circuit.Solution

    master = str(config.DSS_DIR / "Master.dss")
    _text.Command = f'Compile "{master}"'
    _text.Command = f"Set Mode=daily number=1 stepsize={stepsize_minutes}m"
    _text.Command = "Set time=(0,0)"

    all_lines = list(_circuit.Lines.AllNames)
    print(f"[INFO] Master.dss: {len(all_lines)} lines (MV + LV)")

    # --- normamps and phase count per line ---
    line_info = {}
    for ln in all_lines:
        _circuit.Lines.Name = ln
        try:
            amp = float(_circuit.ActiveElement.Properties("normamps").Val)
        except Exception:
            amp = np.nan
        try:
            nph = int(_circuit.Lines.Phases)
        except Exception:
            nph = 3
        line_info[ln] = {"normamps": amp, "nphases": nph}

    # --- timeseries loop ---
    loading_rows = []
    for _ in tqdm(range(npts), desc="DSS balanced all-lines loading"):
        _sol.Solve()
        row = {}
        for ln in all_lines:
            _circuit.Lines.Name = ln
            info = line_info[ln]
            amp  = info["normamps"]
            nph  = info["nphases"]
            if np.isnan(amp) or amp <= 0:
                row[ln] = np.nan
                continue
            mags = _circuit.ActiveElement.CurrentsMagAng
            # mags = [mag0, ang0, mag1, ang1, ...] for sending-end conductors
            # Only take the first nphases conductors (skip neutral)
            phase_mags = [mags[2 * k] for k in range(min(nph, len(mags) // 2))]
            row[ln] = max(phase_mags) / amp * 100.0 if phase_mags else np.nan
        loading_rows.append(row)

    loading_pct = pd.DataFrame(loading_rows)
    loading_pct.index.name = "time_step"

    time_index = pd.date_range("2021-01-01 00:00", periods=npts, freq=f"{stepsize_minutes}min")
    loading_pct.insert(0, "time", time_index)

    loading_pct.to_csv(out_csv, index=False)
    return loading_pct


# ══════════════════════════════════════════════════════════════════════════════
# Main execution
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    import os as _os_c
    _npts_c    = int(_os_c.environ.get("NANDO_VALIDATION_STEPS", "48"))
    _cache_key = f"{config.SELECTED_DAY}_{_npts_c}"
    _sentinel  = config.RESULTS_DIR / ".balanced_cache.txt"
    if _sentinel.exists() and _sentinel.read_text().strip() == _cache_key:
        print(f"[CACHE] Balanced DSS results current for day={config.SELECTED_DAY}, steps={_npts_c} — skipping.")
        import sys as _sys; _sys.exit(0)

    # ── 1. Load network data from Excel ───────────────────────────────────────
    print("\033[1;92mLoading network data from Excel...\033[0m")
    net_data_obj = NetworkData(
        name=config.NETWORK_OPTION,
        data_location=str(config.NETWORK_XLSX),
    )
    network_data = net_data_obj.data
    network_gis  = net_data_obj.network_plotting()

    # ── 2. Build DSS network ──────────────────────────────────────────────────
    print("\033[1;92mNetwork building started.\033[0m")
    driver = DSSDriver(data=network_data, gis_data=network_gis)
    driver.basic_opendss_actions()
    driver.voltage_source()
    driver.mv_net_tx()
    driver.line_codes()
    driver.connections()
    try:
        driver.capacitors()
    except Exception:
        pass
    try:
        driver.mv_txs()
    except Exception:
        pass
    driver.lv_tx()
    driver.lv_nets()
    selected_day = driver.lv_load_mod(config.SELECTED_DAY)
    driver.print_selected_date(selected_day)
    driver.other_opendss_commands()
    print("\033[1;92mNetwork building completed.\033[0m")

    # ── 3. Run daily timeseries ───────────────────────────────────────────────
    Vdata, Idata, Sdata_txs = run_daily(driver)

    # ── 4. OUTPUT 1: All buses – cleaned voltage data ─────────────────────────
    # Keep only nodes that have at least one timestep > 100 V (removes dead/
    # inactive nodes from the dataset).
    VOLTAGE_THRESHOLD = 100.0  # Volts
    cols_keep    = Vdata.columns[Vdata.astype(float).max(axis=0) > VOLTAGE_THRESHOLD]
    Vdata_clean  = Vdata[cols_keep].astype(float)
    Vdata_clean.index.name = "timestep"

    out_buses = config.DSS_VDATA_CLEAN
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    Vdata_clean.to_csv(out_buses)
    print(f"[OK] Saved all buses (clean) → {out_buses.name}  shape={Vdata_clean.shape}")

    # ── 5. OUTPUT 2: All lines loading [%] ────────────────────────────────────
    import os as _os_main
    _npts_main = int(_os_main.environ.get("NANDO_VALIDATION_STEPS", "48"))
    out_lines = str(config.EXCELS_DIR / "all_lines_loading_percent.csv")
    loading_pct = export_all_line_loading_csv(
        out_csv=out_lines,
        npts=_npts_main,
        stepsize_minutes=config.TIME_RES_MIN,
    )
    print(f"[OK] Saved all lines loading → all_lines_loading_percent.csv  shape={loading_pct.shape}")

    # ── 6. OUTPUT 3: Mean voltage per bus in p.u. ─────────────────────────────
    SOURCE_BASE = 66000 / np.sqrt(3)   # ~38105 V  (source / 66 kV side)
    MV_BASE     = 22000 / np.sqrt(3)   # ~12702 V  (MV 22 kV)
    LV_BASE     =   400 / np.sqrt(3)   #   ~231 V  (LV 400 V)

    bus_groups: dict = {}
    for col in Vdata_clean.columns:
        base_bus = col.split(".")[0]
        bus_groups.setdefault(base_bus, []).append(col)

    result = {}
    for bus, cols in bus_groups.items():
        v_mean = Vdata_clean[cols].mean(axis=1) if len(cols) == 3 else Vdata_clean[cols[0]]
        bus_lower = bus.lower()
        if "source" in bus_lower:
            v_base = SOURCE_BASE
        elif "lv" in bus_lower:
            v_base = LV_BASE
        else:
            v_base = MV_BASE
        result[bus] = v_mean / v_base

    df_vm_pu = pd.DataFrame(result)
    df_vm_pu.index.name = "timestep"

    out_pu = config.EXCELS_DIR / "Vmean_vm_pu_with_source.csv"
    df_vm_pu.to_csv(out_pu)
    print(f"[OK] Saved mean vm_pu per bus → {out_pu.name}  shape={df_vm_pu.shape}")

    # ── 7. OUTPUT 4: Trafo loading [%] ───────────────────────────────────────
    # Build kVA map: DSS trafo name (lowercase) -> rated kVA from Excel lvtx sheet
    lvtx_df = network_data["lvtx"].copy().reset_index(drop=True)
    kva_map = {}
    for _, row in lvtx_df.iterrows():
        dss_name = f"mv_f0_lv_{row['Substation_ID']}".lower()
        try:
            kva_map[dss_name] = float(row["kvas_primary"])
        except (ValueError, TypeError):
            pass

    S_lv_txs_out = Sdata_txs.copy()
    S_lv_txs_out.index = range(len(S_lv_txs_out))
    S_lv_txs_out.index.name = "timestamp"
    S_lv_txs_out.columns = [str(c).lower() for c in S_lv_txs_out.columns]
    S_lv_txs_out = S_lv_txs_out.apply(pd.to_numeric, errors="coerce")

    loading_percent_tx = S_lv_txs_out.copy()
    missing_tx = []
    for tx in loading_percent_tx.columns:
        cap = kva_map.get(tx, np.nan)
        if np.isnan(cap) or cap <= 0:
            loading_percent_tx[tx] = np.nan
            missing_tx.append(tx)
        else:
            loading_percent_tx[tx] = 100.0 * loading_percent_tx[tx] / cap

    summary_tx = pd.DataFrame(index=S_lv_txs_out.columns)
    summary_tx.index.name = "trafo"
    summary_tx["rated_kVA"]     = [kva_map.get(tx, np.nan) for tx in summary_tx.index]
    summary_tx["max_loading_%"] = loading_percent_tx.max(axis=0, skipna=True)
    summary_tx["mean_loading_%"]= loading_percent_tx.mean(axis=0, skipna=True)
    summary_tx["hours_over_100%"] = (loading_percent_tx > 100).sum(axis=0) * (config.TIME_RES_MIN / 60.0)

    missing_tx_df = pd.DataFrame({"missing_trafos_in_ratings": missing_tx})

    out_trafo_xlsx = config.DSS_TRAFO_LOADING_XLSX
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(str(out_trafo_xlsx), engine="openpyxl") as writer:
        S_lv_txs_out.to_excel(writer, sheet_name="S_lv_txs_kVA")
        loading_percent_tx.to_excel(writer, sheet_name="loading_percent")
        summary_tx.to_excel(writer, sheet_name="summary")
        missing_tx_df.to_excel(writer, sheet_name="missing_in_ratings", index=False)
    print(f"[OK] Saved trafo loading     → {out_trafo_xlsx.name}  shape={loading_percent_tx.shape}")
    if missing_tx:
        print(f"     WARNING: {len(missing_tx)} trafos δεν βρέθηκαν kVA. Δες sheet 'missing_in_ratings'.")

    print("\n\033[1;92m[DONE] Balanced timeseries complete.\033[0m")
    print(f"  Output 1 (all buses):       {out_buses}")
    print(f"  Output 2 (all lines):       {out_lines}")
    print(f"  Output 3 (mean vm_pu):      {out_pu}")
    print(f"  Output 4 (trafo loading):   {out_trafo_xlsx}")
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _sentinel.write_text(_cache_key)
