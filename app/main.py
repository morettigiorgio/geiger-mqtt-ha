import serial
import time
import struct
from collections import deque
import paho.mqtt.client as mqtt
import json
import os

PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB1")
BAUDRATE = int(os.getenv("SERIAL_BAUDRATE", "115200"))
TIMEOUT = int(os.getenv("SERIAL_TIMEOUT", "1"))

CPM_TO_USVH = float(os.getenv("CPM_TO_USVH", "153.0"))  # GQ constant for SBM-20
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", "10"))  # number of samples for averaging

# --- MQTT CONFIGURATION (from environment variables) ---
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_TOPIC_CPM = os.getenv("MQTT_TOPIC_CPM", "geiger/cpm")
MQTT_TOPIC_USVH = os.getenv("MQTT_TOPIC_USVH", "geiger/usvh")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "geiger-detector")

def send_cmd(ser, cmd, resp_len=0, is_ascii=False):
    """
    Send RFC1801 command to GMC and read response.
    - cmd: command string (e.g. 'GETVER')
    - resp_len: number of expected bytes (0 = no response)
    - is_ascii: if True decode as ASCII
    """
    ser.reset_input_buffer()
    packet = f"<{cmd}>>".encode("ascii")
    ser.write(packet)
    time.sleep(0.1)

    if resp_len <= 0:
        return None

    data = ser.read(resp_len)
    if not data or len(data) < resp_len:
        return None

    return data.decode("ascii", errors="ignore").strip() if is_ascii else data

def read_variable_ascii(ser, cmd, timeout=1.0):
    """
    For RFC1801 commands that return variable-length ASCII,
    read until timeout or end indicator ('>>')."""
    ser.reset_input_buffer()
    ser.write(f"<{cmd}>>".encode("ascii"))
    deadline = time.time() + timeout
    buffer = b""
    while time.time() < deadline:
        chunk = ser.read(1)
        if chunk:
            buffer += chunk
        else:
            break
    return buffer.decode("ascii", errors="ignore").strip()

def on_mqtt_connect(client, userdata, flags, rc, *args, **kwargs):
    """MQTT connection callback"""
    if rc == 0:
        print("[MQTT] Connected to broker")
    else:
        print(f"[MQTT] Connection error, code: {rc}")

def on_mqtt_disconnect(client, userdata, rc, *args, **kwargs):
    """MQTT disconnection callback"""
    # Only print if it's a real error (rc != 0 and not a normal client-initiated disconnect)
    if rc != 0 and not str(rc).startswith("DisconnectFlags"):
        print(f"[MQTT] Unexpected disconnection, code: {rc}")

def publish_sensor(client, topic, value, min_val, avg_val, max_val):
    """Publish sensor data in JSON format"""
    payload = {
        "value": value,
        "min": min_val,
        "avg": avg_val,
        "max": max_val
    }
    client.publish(topic, json.dumps(payload), qos=1)

def main():
    # --- SETUP MQTT ---
    # Try VERSION2 first, fallback to default for older paho-mqtt versions
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
    except (AttributeError, TypeError):
        client = mqtt.Client(client_id=MQTT_CLIENT_ID)
    
    client.on_connect = on_mqtt_connect
    client.on_disconnect = on_mqtt_disconnect
    try:
        # Configure credentials if provided
        if MQTT_USER and MQTT_PASSWORD:
            client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        print(f"[MQTT] Connecting to {MQTT_BROKER}:{MQTT_PORT}")
        if MQTT_USER:
            print(f"[MQTT] Authenticated as: {MQTT_USER}")
    except Exception as e:
        print(f"[MQTT] Error: {e}")
        client = None

    # --- SETUP SERIAL ---
    ser = serial.Serial(PORT, BAUDRATE, timeout=TIMEOUT)
    try:
        print(f"Connected to {PORT} @ {BAUDRATE}")
        time.sleep(0.5)

        # --- DISABLE HEARTBEAT ---
        print("Disabling heartbeat (HEARTBEAT0)")
        send_cmd(ser, "HEARTBEAT0")

        # --- VERSION ASCII ---
        version = read_variable_ascii(ser, "GETVER", timeout=1.5)
        print("Version:", version if version else "<no response>")

        # --- BATTERY ASCII (5 bytes) ---
        batt = send_cmd(ser, "GETVOLT", resp_len=5, is_ascii=True)
        print("Battery:", batt if batt else "<no response>")

        # --- SERIAL NUMBER (7 bytes) ---
        raw_ser = send_cmd(ser, "GETSERIAL", resp_len=7)
        if raw_ser:
            serial_num = raw_ser.hex().upper()
            print("Serial:", serial_num)
        else:
            print("Serial: no response")

        # --- DATETIME (7 bytes) ---
        raw_dt = send_cmd(ser, "GETDATETIME", resp_len=7)
        if raw_dt:
            yy, mm, dd, hh, mi, ss, aa = raw_dt
            print(f"DateTime: 20{yy:02d}-{mm:02d}-{dd:02d} {hh:02d}:{mi:02d}:{ss:02d}")
        else:
            print("DateTime: no response")

        print("\nStarting continuous reading (Ctrl+C to exit)...\n")

        # --- BUFFER FOR MIN/AVG/MAX ---
        cpm_history = deque(maxlen=WINDOW_SIZE)
        usvh_history = deque(maxlen=WINDOW_SIZE)

        # --- CONTINUOUS LOOP ---
        while True:
            # --- CPM (4 bytes big endian) ---
            raw_cpm = send_cmd(ser, "GETCPM", resp_len=4)
            if raw_cpm:
                cpm = struct.unpack(">I", raw_cpm)[0]
                # Calculate µSv/h
                usvh = round(cpm / CPM_TO_USVH, 4)
                
                # Add to history buffers
                cpm_history.append(cpm)
                usvh_history.append(usvh)
                
                # Calculate min, average, and max
                cpm_min = min(cpm_history) if cpm_history else 0
                cpm_avg = round(sum(cpm_history) / len(cpm_history), 2) if cpm_history else 0
                cpm_max = max(cpm_history) if cpm_history else 0
                usvh_min = round(min(usvh_history), 4) if usvh_history else 0
                usvh_avg = round(sum(usvh_history) / len(usvh_history), 4) if usvh_history else 0
                usvh_max = round(max(usvh_history), 4) if usvh_history else 0
                
                print(f"CPM: {cpm:6d} ({cpm_min:6d}, {cpm_avg:6.2f}, {cpm_max:6d}) | "
                      f"µSv/h: {usvh:.4f} ({usvh_min:.4f}, {usvh_avg:.4f}, {usvh_max:.4f})")
                
                # --- PUBLISH TO MQTT ---
                if client:
                    publish_sensor(client, MQTT_TOPIC_CPM, cpm, cpm_min, cpm_avg, cpm_max)
                    publish_sensor(client, MQTT_TOPIC_USVH, usvh, usvh_min, usvh_avg, usvh_max)
            else:
                print("CPM: no response")

            time.sleep(1)  # Read every second

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        ser.close()
        print("Serial port closed")
        if client:
            client.loop_stop()
            client.disconnect()
            print("Disconnected from MQTT")

if __name__ == "__main__":
    main()
