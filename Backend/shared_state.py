"""Config constants and in-memory runtime state shared across routers."""
from pathlib import Path
from collections import defaultdict, deque


DATA_FILE = Path("data/networks.json")
PLOTS_DIR = Path("data/plots")
RESULTS_DIR = Path("data/results")


# ── Edge device in-memory state ───────────────────────────────────────────────
# Works without PostgreSQL; DB is a persistence side-effect when available.
_devices: dict[str, dict] = {}                                # device_id → info dict
_edge_nodes: dict[str, dict] = {}                             # node_id → {id, name}
_telemetry: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))  # device_id → readings
_ws_subs: dict[str, set] = defaultdict(set)                  # device_id → active WebSockets


# Path to the Conversion/opendss_conversion directory (sibling of Backend in the repo root)
NANDO_ROOT = Path(__file__).parent.parent / "Conversion" / "opendss_conversion"


# Full-year load profile arrays for OpenDSS networks (shape: (N_profiles, 365, 48))
_RES_NPY = NANDO_ROOT / "excels" / "Res_load_data_30min_res.npy"
_COM_NPY = NANDO_ROOT / "excels" / "Com_load_data_30min_res.npy"


from generate_networks import style_traces, build_plot_html

try:
    from generate_networks import COLORS, style_traces, build_plot_html, compute_min_height
    _PLOT_HELPERS_AVAILABLE = True
except Exception:
    _PLOT_HELPERS_AVAILABLE = False


NANDO_NETWORK_NAMES = {
    "1": "Rural_SMR8",
    "2": "Rural_KLO14",
    "3": "Urban_HPK11",
    "4": "Urban_CRE21",
}


# Violation thresholds — must match the frontend constants in violations-overview.ts.
V_LOWER = 0.94
V_UPPER = 1.06
LOAD_LIMIT = 100.0
