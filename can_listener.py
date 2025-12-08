# can_listener.py
import can
import threading

latest_messages = []

def can_listener():
    bus = can.Bus(channel="can0", interface="socketcan")
    for msg in bus:
        latest_messages.append({
            "id": hex(msg.arbitration_id),
            "data": list(msg.data)
        })
