"""
CANiac Duo — Hybrid Dashboard
CST timestamps • Multi-machine tabs • Manual + Auto message generation
"""

# --- Compatibility patch for Python 3.13 (pkgutil.find_loader removed) ---
import pkgutil, importlib.util
if not hasattr(pkgutil, "find_loader"):
    pkgutil.find_loader = lambda name: importlib.util.find_spec(name)

import random, struct
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from dash import Dash, html, dcc, Input, Output, State, ctx, dash_table


import can
import threading
import queue

from flask import Response

CAN_CHANNEL = "can0"
CAN_IFACE   = "socketcan"

bus = can.Bus(channel=CAN_CHANNEL, interface=CAN_IFACE, receive_own_messages=False)

rx_queue = queue.Queue()

# -------------------------------------------------------------------------
# Helper: CST timestamps
def now_ms():
    cst = ZoneInfo("America/Chicago")
    return datetime.now(cst).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " CST"

# -------------------------------------------------------------------------
# Fake CAN database
FAKE_MESSAGE_MAP = {
    0x100: {"name": "Engine Module", "signal": "RPM", "format": ">H", "scale": 0.125, "unit": "RPM"},
    0x200: {"name": "Battery Module", "signal": "Voltage", "format": ">H", "scale": 0.1, "unit": "V"},
    0x300: {"name": "Cooling Module", "signal": "Temperature", "format": ">b", "scale": 1.0, "unit": "°C"},
}

def interpret_can_message(msg):
    """Decode a CAN frame into human-readable form (fake demo)."""
    try:
        mid = int(msg["id"], 16)
        entry = FAKE_MESSAGE_MAP.get(mid)
        if not entry:
            return "(unknown)", None
        raw = bytes(int(x, 16) for x in msg["data"].split())
        if len(raw) < struct.calcsize(entry["format"]):
            return "(short data)", None
        val = struct.unpack(entry["format"], raw[:struct.calcsize(entry["format"])])[0] * entry["scale"]
        return f"{entry['signal']}: {val:.2f} {entry['unit']}", val
    except Exception as e:
        return f"(decode error: {e})", None

def random_can_message():
    msg_id = random.choice([0x100, 0x200, 0x300])
    dlc = 2
    data = [f"{random.randint(0,255):02X}" for _ in range(dlc)]
    msg = {
        "timestamp": now_ms(),
        "id": hex(msg_id),
        "extended": False,
        "dlc": dlc,
        "data": " ".join(data)
    }
    interp, val = interpret_can_message(msg)
    msg["interpreted"], msg["value"] = interp, val
    return msg


# Background receive loop
def can_rx_worker():
    while True:
        msg = bus.recv(timeout=1.0)   # blocking read
        if msg is None:
            continue

        # Convert python-can msg into your dashboard format
        data_hex = " ".join(f"{b:02X}" for b in msg.data)

        frame = {
            "timestamp": now_ms(),
            "id": hex(msg.arbitration_id),
            "extended": msg.is_extended_id,
            "dlc": msg.dlc,
            "data": data_hex,
        }

        interp, val = interpret_can_message(frame)
        frame["interpreted"], frame["value"] = interp, val

        rx_queue.put(frame)

# Start receiver thread
threading.Thread(target=can_rx_worker, daemon=True).start()

# -------------------------------------------------------------------------
# Dash setup

app = Dash(__name__)
server = app.server

app.layout = html.Div([
    html.H2("CANiac Duo — CAN Dashboard 1"),

    # --- Manual controls block ---
    html.Div([
        html.Div([
            html.H4("Send a fake CAN message"),
            html.Label("Message ID (hex or decimal):"),
            dcc.Input(id="input-id", type="text", value="0x100"),
            html.Br(),
            html.Label("Extended ID?"),
            dcc.RadioItems(id="input-extended",
                options=[{"label":"Standard (11-bit)","value":False},
                         {"label":"Extended (29-bit)","value":True}],
                value=False, inline=True),
            html.Br(),
            html.Label("DLC (0–8):"),
            dcc.Input(id="input-dlc", type="number", min=0, max=8, value=2),
            html.Br(),
            html.Label("Data (space-separated hex bytes):"),
            dcc.Input(id="input-data", type="text", placeholder="00 FF", value=""),
            html.Br(),
            html.Button("Send Message", id="btn-send", n_clicks=0, style={"marginTop":"6px"}),
            html.Button("Clear Log", id="btn-clear", n_clicks=0, style={"marginLeft":"6px"}),
            html.Button("Download CSV", id="btn-download", n_clicks=0, style={"marginLeft":"6px"}),
            html.Button("Refresh Data", id="btn-refresh", n_clicks=0, style={"marginLeft":"6px"}),
            dcc.Download(id="download-log"),
            html.Div(id="send-feedback", style={"marginTop":"6px","color":"green"})
        ], style={"padding":"10px","flex":"1","border":"1px solid #ddd","borderRadius":"6px"}),

        html.Div([
            html.H4("Auto-generate messages"),
            html.Label("Enable auto-generator:"),
            dcc.RadioItems(id="auto-enable",
                options=[{"label":"Off","value":False},{"label":"On","value":True}],
                value=False, inline=True),
            html.Br(),
            html.Label("Messages per second:"),
            dcc.Slider(id="auto-rate", min=1, max=50, step=1, value=5,
                       marks={1:"1",5:"5",10:"10",25:"25",50:"50"}),
            html.Br(),
            html.Label("Filter ID prefix (hex):"),
            dcc.Input(id="filter-prefix", type="text", placeholder="e.g. 0x1", value=""),
            html.Br(),
            html.Div(id="auto-status", style={"marginTop":"6px","color":"#333"})
        ], style={"padding":"10px","flex":"1","marginLeft":"10px",
                  "border":"1px solid #ddd","borderRadius":"6px"})
    ], style={"display":"flex","gap":"10px","flexWrap":"wrap"}),

    html.Hr(),

    # --- Tabs for Overview + per-machine views ---
    dcc.Tabs(id="tabs", value="overview", children=[
        dcc.Tab(label="Overview", value="overview")
    ]),
    html.Div(id="tab-content", style={"marginTop":"10px"}),

    # --- Data storage + timers ---
    dcc.Store(id="store-log", data=[]),
    dcc.Interval(id="interval-auto", interval=1000, n_intervals=0)
], style={"maxWidth":"1100px","margin":"12px auto","fontFamily":"Arial, sans-serif"})

# -------------------------------------------------------------------------
# Callbacks

# Auto-generator enable/disable
@app.callback(
    Output("interval-auto","disabled"),
    Output("auto-status","children"),
    Input("auto-enable","value"),
    Input("auto-rate","value")
)
def toggle_auto(enable, rate):
    if enable:
        return False, f"Auto-generator ON (~{rate} msg/s)"
    return True, "Auto-generator OFF"

# Generate / send / clear
@app.callback(
    Output("store-log","data"),
    Output("send-feedback","children"),
    Input("interval-auto","n_intervals"),
    Input("btn-send","n_clicks"),
    Input("btn-clear","n_clicks"),
    Input("btn-refresh","n_clicks"),
    State("store-log","data"),
    State("auto-enable","value"),
    State("auto-rate","value"),
    State("input-id","value"),
    State("input-extended","value"),
    State("input-dlc","value"),
    State("input-data","value"),
    prevent_initial_call=True
)
def update_log(nint, nsend, nclear, nrefresh, log, auto_on, rate,
               mid_in, ext_in, dlc_in, data_in):
    trig = ctx.triggered_id
    log = list(log or [])
    # Pull all received CAN frames into log
    while not rx_queue.empty():
        log.append(rx_queue.get())

    if trig == "btn-clear":
        return [], "Log cleared."
    if trig == "btn-refresh":
        return log[-1000:], f"Refresh"
    if trig == "btn-send":
        try:
            mid = int(str(mid_in).strip(), 0)
            dlc = max(0,min(8,int(dlc_in or 0)))
            bytes_in = str(data_in).strip().split()
            if not bytes_in:
                bytes_in = [f"{random.randint(0,255):02X}" for _ in range(dlc)]
            msg = {"timestamp":now_ms(),"id":hex(mid),
                   "extended":ext_in,"dlc":dlc,"data":" ".join(bytes_in)}
            interp,val = interpret_can_message(msg)
            msg["interpreted"],msg["value"]=interp,val
            log.append(msg)
            return log[-1000:], f"Sent {hex(mid)}"
        except Exception as e:
            return log, f"Error: {e}"
    if trig == "interval-auto" and auto_on:
        for _ in range(rate):
            log.append(random_can_message())
        return log[-1000:], f"Auto +{rate}"
    return log, ""

# Build tab list dynamically
@app.callback(Output("tabs","children"), Input("store-log","data"))
def build_tabs(log):
    tabs=[dcc.Tab(label="Overview",value="overview")]
    ids=sorted({m["id"] for m in log})
    for mid in ids:
        name=FAKE_MESSAGE_MAP.get(int(mid,16),{}).get("name",f"Device {mid}")
        tabs.append(dcc.Tab(label=f"{name} ({mid})",value=mid))
    return tabs

# Render tab content
@app.callback(Output("tab-content","children"), Input("tabs","value"), State("store-log","data"))
def render_tab(tab, log):
    df=pd.DataFrame(log or [])
    if df.empty:
        return html.Div("No data yet.")
    if tab=="overview":
        counts=df["id"].value_counts().reset_index()
        counts.columns=["id","count"]
        return html.Div([
            html.H4("Message Counts"),
            dash_table.DataTable(data=counts.to_dict("records"),
                columns=[{"name":c,"id":c} for c in counts.columns],
                style_table={"maxHeight":"250px","overflowY":"scroll"},
                style_cell={"fontFamily":"monospace","padding":"4px"}),
            html.Hr(),
            html.H4("Recent Messages"),
            dash_table.DataTable(
                data=df.sort_values("timestamp",ascending=False).to_dict("records"),
                columns=[{"name":c,"id":c} for c in ["timestamp","id","data","interpreted"]],
                page_size=10,
                style_cell={"fontFamily":"monospace","padding":"4px"})
        ])
    # Machine-specific
    sub=df[df["id"]==tab]
    if sub.empty:
        return html.Div(f"No messages for {tab}.")
    mid=int(tab,16)
    entry=FAKE_MESSAGE_MAP.get(mid,{"signal":"Value","unit":""})
    fig={
        "data":[{"x":sub["timestamp"],"y":sub["value"],"type":"lines","name":entry["signal"]}],
        "layout":{"title":f"{entry['name']} ({tab}) — {entry['signal']}",
                  "xaxis":{"title":"Time"},
                  "yaxis":{"title":entry["unit"]}}
    }
    return dcc.Graph(figure=fig, style={"height":"400px"})

# Download CSV
@app.callback(Output("download-log","data"),
              Input("btn-download","n_clicks"),
              State("store-log","data"),
              prevent_initial_call=True)
def download_csv(n,log):
    df=pd.DataFrame(log or [])
    if df.empty:
        return dcc.send_data_frame(pd.DataFrame().to_csv,"can_log_empty.csv")
    filename=f"can_log_{datetime.now(ZoneInfo('America/Chicago')).strftime('%Y%m%dT%H%M%S')}_CST.csv"
    return dcc.send_data_frame(df.to_csv,filename,index=False)

# -------------------------------------------------------------------------

if __name__=="__main__":
    app.run(debug=False, host="0.0.0.0", port=8050)
