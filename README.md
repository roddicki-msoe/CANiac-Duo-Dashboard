# CANiac Duo Dashboard

This project simulates and visualizes CAN traffic using [Dash](https://dash.plotly.com/).
It supports manual message creation, automatic fake CAN generation, and per-ID visualization.

## Features
- CST timestamps
- Overview + per-machine tabs
- Pause / Resume live updates (Disabled for now)
- Export CAN logs to CSV
- Modular fake CAN decoding map

## Run locally
```bash
git clone https://github.com/YOUR_USERNAME/can_dashboard.git
cd can_dashboard
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
