# /// script
# dependencies = [
#   "dotenv",
#   "requests",
#   "urllib3",
# ]
# ///

import dotenv
import requests
import urllib3

# Suppress SSL warnings if you use a self-signed certificate on your gateway
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONFIGURATION ---
UNIFI_HOST = "10.0.0.1"  # Your Cloud Gateway Local IP
UNIFI_USER = dotenv.get_key(".env", "UNIFI_USER")
UNIFI_PASS = dotenv.get_key(".env", "UNIFI_PASS")
SITE_ID = "default"         # Typically 'default'

# Find the MAC address of your US-8-60W switch in the UniFi Devices tab
SWITCH_MAC = "e0:63:da:2e:80:74"

# Map camera IP addresses to their specific port index on the US-8-60W
# Note: On the US-8-60W, only ports 5, 6, 7, and 8 provide PoE.
CAMERAS_TO_MONITOR = [
    {"mac": "1c:6a:1b:8c:45:3f", "ip": "10.0.3.248", "port": 5, "name": "Front Entry and Yard"},
    {"mac": "28:70:4e:1d:77:13", "ip": "10.0.3.155", "port": 6, "name": "BBQ area and Pool Slider"},
    {"mac": "28:70:4e:1d:73:d1", "ip": "10.0.3.146", "port": 7, "name": "Courtyard and Sliders"},
    {"mac": "1c:6a:1b:8c:47:67", "ip": "10.0.3.14", "port": 8, "name": "Pool Spa and Rear Fence Line"},
]

BASE_URL = f"https://{UNIFI_HOST}"

# ---------------------
def get_unifi_session():
    """Authenticates and returns an active API session with CSRF tokens."""
    session = requests.Session()
    session.verify = False
    session.headers.update({
            "Referer": f"https://{UNIFI_HOST}/",
            "Content-Type": "application/json"
        })
    try:
        login_resp = session.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": UNIFI_USER, "password": UNIFI_PASS},
            timeout=10)
        if login_resp.status_code == 200:
            if "X-CSRF-Token" in login_resp.headers:
                session.headers.update({"X-CSRF-Token": login_resp.headers["X-CSRF-Token"]})
            return session
        else:
            print(f"[ERROR] Login failed. HTTP {login_resp.status_code}")
            #print(f"Reason: {login_resp.reason}")
            #print(f"Response: {login_resp.text}")
            #print(f"Headers returned: {dict(login_resp.headers)}")
            return None
    except Exception as e:
        print(f"[ERROR] Could not connect to UniFi Gateway: {e}")
    return None

def check_cameras_and_cycle():
    session = get_unifi_session()
    if not session:
        print("[ERROR] No active session.")
        return

    try:
        # Fetch the entire online/offline client database known to the controller
        client_url = f"{BASE_URL}/proxy/network/api/s/{SITE_ID}/stat/sta"
        response = session.get(client_url, timeout=10)

        if response.status_code != 200:
            print(f"[ERROR] Failed to fetch clients. HTTP {response.status_code}")
            return

        #clients = {c['mac'].lower(): c for c in response.json().get('data', [])}
        all_devices = {u['mac'].lower(): u for u in response.json().get('data', [])}

        for cam in CAMERAS_TO_MONITOR:
            cam_mac = cam["mac"].lower()

            if cam_mac not in all_devices:
                print(f"[WARN] {cam['name']} ({cam_mac}) not found in UniFi database. Check MAC.")
                continue

            device_data = all_devices[cam_mac]
            # Read UniFi's explicit online status flag
            # In the rest/user endpoint, it's explicitly boolean True or False
            is_online = is_camera_online(device_data)
            print(f"[{cam['name']}] Status flag: {'ONLINE' if is_online else 'OFFLINE'}")
            if not is_online:
                print(f"[ALERT] {cam['name']} is explicitly flagged OFFLINE. Cycling port {cam['port']}...")
                # Issue Power-Cycle Command
                power_cycle_poe_port(session, cam["port"])

    except Exception as e:
        print(f"[ERROR] Error during processing: {e}")

def is_camera_online(device_data):
    # Navigate into the nested dictionary safely using .get()
    ucore_info = device_data.get('unifi_device_info_from_ucore', {})

    # Check the nested properties
    device_state = ucore_info.get('device_state', '').upper()          # e.g., 'CONNECTED'
    ucore_status = ucore_info.get('ucore_device_status', '').lower()   # e.g., 'online'

    # A camera is online if either indicator shows it's active
    return (device_state == 'CONNECTED' or ucore_status == 'online')

def power_cycle_poe_port(session, port_index):
    cmd_url = f"{BASE_URL}/proxy/network/api/s/{SITE_ID}/cmd/devmgr"
    cmd_payload = {
        "mac": SWITCH_MAC.lower(),
        "port_idx": int(port_index),
        "cmd": "power-cycle"
    }
    cmd_resp = session.post(cmd_url, json=cmd_payload, timeout=10)

    if cmd_resp.status_code == 200:
        print(f"[SUCCESS] Port {port_index} power cycled.")
    else:
        print(f"[ERROR] Power cycle command failed: {cmd_resp.text}")

if __name__ == "__main__":
    check_cameras_and_cycle()
