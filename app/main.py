import serial
import time
import struct
from collections import deque
import paho.mqtt.client as mqtt
import json
import os
import logging
from datetime import datetime
import threading

serial_lock = threading.RLock() # Reentrant lock to avoid deadlock

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# level map: Paho -> Python Logging
MQTT_LOG_MAP = {
    mqtt.MQTT_LOG_DEBUG: logging.DEBUG,
    mqtt.MQTT_LOG_INFO: logging.INFO,
    mqtt.MQTT_LOG_NOTICE: logging.INFO, # 'Notice' don't exist in Python, map to INFO
    mqtt.MQTT_LOG_WARNING: logging.WARNING,
    mqtt.MQTT_LOG_ERR: logging.ERROR,
}

PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB1")
BAUDRATE = int(os.getenv("SERIAL_BAUDRATE", "115200"))
TIMEOUT = int(os.getenv("SERIAL_TIMEOUT", "1"))

CPM_TO_USVH = float(os.getenv("CPM_TO_USVH", "153.0"))  # GQ constant for SBM-20
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", "10"))  # number of samples for averaging

# --- DATA VALIDATION ---
MAX_CPM = int(os.getenv("MAX_CPM", "100000"))  # Max reasonable CPM value (filter outliers)
MAX_CPM_JUMP = float(os.getenv("MAX_CPM_JUMP", "5.0"))  # Max multiplier for rate of change

# --- MQTT CONFIGURATION (from environment variables) ---
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_TOPIC_CPM = os.getenv("MQTT_TOPIC_CPM", "geiger/cpm")
MQTT_TOPIC_USVH = os.getenv("MQTT_TOPIC_USVH", "geiger/usvh")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "geiger-detector")
MQTT_PUBLISH_INTERVAL = int(os.getenv("MQTT_PUBLISH_INTERVAL", "1"))  # seconds between MQTT publishes
MQTT_TOPIC_SPEAKER = os.getenv("MQTT_TOPIC_SPEAKER", "geiger/speaker")  # Topic for speaker control (set/state)

def validate_cpm(cpm, cpm_history):
    """
    Validate CPM reading against:
    1. Absolute limits (MAX_CPM)
    2. Statistical outliers (3-sigma rule based on history)
    
    Returns (is_valid, reason)
    """
    # Check absolute maximum
    if cpm < 0 or cpm > MAX_CPM:
        return False, f"exceeds absolute limit ({MAX_CPM})"
    
    # Check statistical outliers if we have history
    if len(cpm_history) > 2:
        mean = sum(cpm_history) / len(cpm_history)
        variance = sum((x - mean) ** 2 for x in cpm_history) / len(cpm_history)

        if abs(cpm - mean) < 5:
            return True, "OK"   # Negligible difference

        std_dev = variance ** 0.5
        effective_std_dev = max(std_dev, 5.0) # at least 5.0 of tolerance
        
        # 3-sigma rule: reject values beyond 3 standard deviations
        if std_dev > 0:
            z_score = abs(cpm - mean) / effective_std_dev
            if z_score > 3.0:
                return False, f"statistical outlier (z={z_score:.2f}, mean={mean:.1f}±{std_dev:.1f})"
    
    return True, "OK"

def send_cmd(ser, cmd, resp_len=0, is_ascii=False):
    """
    Send RFC1801 command to GMC and read response.
    - cmd: command string (e.g. 'GETVER')
    - resp_len: number of expected bytes (0 = no response)
    - is_ascii: if True decode as ASCII
    """
    with serial_lock:
        ser.reset_input_buffer()
        packet = f"<{cmd}>>".encode("ascii")
        ser.write(packet)
        time.sleep(0.15)

        if resp_len <= 0:
            return None

        data = ser.read(resp_len)
        if not data or len(data) < resp_len:
            return None

        return data.decode("ascii", errors="ignore").strip() if is_ascii else data

def read_variable_ascii(ser, cmd, timeout=1.0):
    """
    For RFC1801 commands that return variable-length ASCII,
    read until timeout or end indicator ('>>').
    """
    with serial_lock:
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

def log_config_details(data):
    if not data or len(data) < 512:
        logging.error("data is invalid or missing")
        return

    # B=1 byte, H=2 byte (Unsigned Short), I=4 byte (Unsigned Int), f=float
    config_map = [
        (0,  "B", "Power Status"),
        (1,  "B", "Alarm Sound"),
        (2,  "B", "Speaker Sound"),
        (3,  "B", "Graphic Mode"),
        (4,  "B", "Backlight Timeout (s)"),
        (5,  "B", "Idle Title Mode"),
        (6,  ">H", "Alarm CPM Threshold"),
        (8,  ">H", "Calibration 0 CPM"),
        (10, ">f", "Calibration 0 uSv/h"),
        (14, ">H", "Calibration 1 CPM"),
        (16, ">f", "Calibration 1 uSv/h"),
        (20, ">H", "Calibration 2 CPM"),
        (22, ">f", "Calibration 2 uSv/h"),
        (26, "B", "Idle Display Mode"),
        (27, ">f", "Alarm uSv/h Threshold"),
        (31, "B", "Alarm Type"),
        (32, "B", "Save Data Type"),
        (33, "B", "Swivel Display"),
        (48, "B", "LCD Contrast"),
        (52, "B", "Large Font Mode"),
        (53, "B", "Backlight Level"),
        (54, "B", "Reverse Display"),
        (55, "B", "Motion Detect"),
        (56, "B", "Battery Type"),
        (60, "B", "LED status"),
    ]

    logging.info("--- GMC-500 Configuration Details ---")
    
    for offset, fmt, label in config_map:
        try:
            val = struct.unpack_from(fmt, data, offset)[0]
            if fmt == "B" and offset <= 2:
                val = "ON" if val == 1 else "OFF"
            if fmt == ">f":
                val = round(val, 4)
            logging.info(f"{label:25}: {val}")
        except Exception as e:
            logging.debug(f"Skip {label}: {e}")

    def clean_str(b_slice):
        actual_content = b_slice.split(b'\x00')[0]
        return actual_content.decode('ascii', errors='ignore').strip()

    logging.info(f"{'WiFi SSID':25}: {clean_str(data[69:107])}")
    # logging.info(f"{'WiFi Password':25}: {clean_str(data[107:159])}")
    logging.info(f"{'GMCmap URL':25}: {clean_str(data[160:192])}")
    logging.info(f"{'GMCmap URI':25}: {clean_str(data[192:224])}")
    
    logging.info("-------------------------------------")

def on_mqtt_connect(client, userdata, flags, rc, *args, **kwargs):
    """MQTT connection callback"""
    if rc == 0:
        logging.info("[MQTT] Connected to broker")
    else:
        logging.error(f"[MQTT] Connection error, code: {rc}")

def on_mqtt_disconnect(client, userdata, rc, *args, **kwargs):
    """MQTT disconnection callback"""
    # Only print if it's a real error (rc != 0 and not a normal client-initiated disconnect)
    if rc != 0 and not str(rc).startswith("DisconnectFlags"):
        logging.error(f"[MQTT] Unexpected disconnection, code: {rc}")

def publish_sensor(client, topic, value, min_val, avg_val, max_val):
    """Publish sensor data in JSON format with timestamp"""
    payload = {
        "value": value,
        "min": min_val,
        "avg": avg_val,
        "max": max_val,
        "timestamp": datetime.now().isoformat()
    }
    client.publish(topic, json.dumps(payload), qos=1)

def get_speaker_state_from_device(ser):
    """
    Retrieve current speaker state from device configuration
    Returns True if speaker is enabled, False if disabled, None on error
    """
    config_raw = send_cmd(ser, "GETCFG", resp_len=512)
    if config_raw and len(config_raw) >= 3:
        # Il byte all'offset 2 è lo Speaker Sound
        speaker_bit = struct.unpack_from("B", config_raw, 2)[0]
        return (speaker_bit == 1)
    return None

def set_speaker(ser, enabled):
    """
    Control speaker via RFC1801 protocol
    Returns True if successful (0xAA response)
    """
    cmd = "SPEAKER1" if enabled else "SPEAKER0"
    response = send_cmd(ser, cmd, resp_len=1)
    if response and response[0] == 0xAA:
        state_str = "ON" if enabled else "OFF"
        logging.info(f"[Speaker] Set to {state_str}")
        return True
    else:
        logging.error(f"[Speaker] Failed to set speaker (no response)")
        return False

def on_mqtt_message(client, userdata, msg):
    """
    Handle incoming MQTT messages (speaker control)
    """
    if msg.topic == f"{MQTT_TOPIC_SPEAKER}/set":
        payload = msg.payload.decode().lower()
        requested_state = payload in ["on", "1", "true"]
        
        set_speaker(userdata["serial"], requested_state)
        time.sleep(0.2) 
        
        actual_state = get_speaker_state_from_device(userdata["serial"])
        
        if actual_state is not None:
            userdata["speaker_state"] = actual_state
            publish_speaker_state(client, actual_state)
            logging.info(f"[Speaker] Sync completed. State: {'ON' if actual_state else 'OFF'}")

def publish_speaker_state(client, state):
    """
    Publish speaker state with retain flag
    """
    state_payload = "ON" if state else "OFF"
    client.publish(f"{MQTT_TOPIC_SPEAKER}/state", state_payload, qos=1, retain=True)
    logging.info(f"[Speaker] Published initial state: {state_payload}")

def on_log(client, userdata, level, buf):
    py_level = MQTT_LOG_MAP.get(level, logging.INFO)
    logging.log(py_level, f"MQTT: {buf}")

def main():
    # --- SETUP MQTT ---
    # Try VERSION2 first, fallback to default for older paho-mqtt versions
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
    except (AttributeError, TypeError):
        client = mqtt.Client(client_id=MQTT_CLIENT_ID)
    
    client.on_log = on_log
    client.on_connect = on_mqtt_connect
    client.on_disconnect = on_mqtt_disconnect
    client.on_message = on_mqtt_message
    
    # Prepare userdata for callbacks
    client.user_data_set({
        "serial": None,
        "speaker_state": False
    })
    
    try:
        # Configure credentials if provided
        if MQTT_USER and MQTT_PASSWORD:
            client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        logging.info(f"[MQTT] Connecting to {MQTT_BROKER}:{MQTT_PORT}")
        if MQTT_USER:
            logging.info(f"[MQTT] Authenticated as: {MQTT_USER}")
    except Exception as e:
        logging.error(f"[MQTT] Error: {e}")
        client = None

    # --- SETUP SERIAL ---
    ser = serial.Serial(PORT, BAUDRATE, timeout=TIMEOUT)
    
    # Store serial connection in userdata for callbacks
    if client:
        client.user_data_set({
            "serial": ser,
            "speaker_state": False
        })
    
    # Subscribe to speaker control topic
    if client:
        client.subscribe(f"{MQTT_TOPIC_SPEAKER}/set")
    
    try:
        logging.info(f"Connected to {PORT} @ {BAUDRATE}")
        time.sleep(0.5)

        # --- DISABLE HEARTBEAT ---
        logging.info("Disabling heartbeat (HEARTBEAT0)")
        send_cmd(ser, "HEARTBEAT0")

        # --- VERSION ASCII ---
        version = read_variable_ascii(ser, "GETVER", timeout=1.5)
        logging.info(f"Version: {version if version else '<no response>'}")

        # --- BATTERY ASCII (5 bytes) ---
        batt = send_cmd(ser, "GETVOLT", resp_len=5, is_ascii=True)
        logging.info(f"Battery: {batt if batt else '<no response>'}")
        
        # --- SERIAL NUMBER (7 bytes) ---
        raw_ser = send_cmd(ser, "GETSERIAL", resp_len=7)
        if raw_ser:
            serial_num = raw_ser.hex().upper()
            logging.info(f"Serial: {serial_num}")
        else:
            logging.info("Serial: no response")

        # --- DATETIME (7 bytes) ---
        raw_dt = send_cmd(ser, "GETDATETIME", resp_len=7)
        if raw_dt:
            yy, mm, dd, hh, mi, ss, aa = raw_dt
            logging.info(f"DateTime: 20{yy:02d}-{mm:02d}-{dd:02d} {hh:02d}:{mi:02d}:{ss:02d}")
        else:
            logging.info("DateTime: no response")

        # --- CONFIG (512 bytes) ---
        config_raw = send_cmd(ser, "GETCFG", resp_len=512)
        log_config_details(config_raw)

        # --- PUBLISH INITIAL SPEAKER STATE ---
        if client:
            is_speaker_on = get_speaker_state_from_device(ser)
            if is_speaker_on is not None:
                client.user_data_get()["speaker_state"] = is_speaker_on
                publish_speaker_state(client, is_speaker_on)
                logging.info(f"[Init] Speaker state detected: {'ON' if is_speaker_on else 'OFF'}")
            else:
                logging.warning("[Init] Could not detect initial speaker state")
            time.sleep(0.5)


        logging.debug("\nStarting continuous reading (Ctrl+C to exit)...\n")

        # --- BUFFER FOR MIN/AVG/MAX ---
        cpm_history = deque(maxlen=WINDOW_SIZE)
        usvh_history = deque(maxlen=WINDOW_SIZE)
        last_publish_time = 0

        # --- CONTINUOUS LOOP ---
        while True:
            # --- CPM (4 bytes big endian) ---
            raw_cpm = send_cmd(ser, "GETCPM", resp_len=4)
            if raw_cpm:
                cpm = struct.unpack(">I", raw_cpm)[0]
                
                # Validate CPM reading (before adding to history)
                is_valid, reason = validate_cpm(cpm, cpm_history)
                if not is_valid:
                    logging.warning(f"[WARN] Rejected CPM {cpm:>10d}: {reason}")
                    time.sleep(1)
                    continue
                
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
                
                logging.info(f"CPM: {cpm:6d} ({cpm_min:6d}, {cpm_avg:6.2f}, {cpm_max:6d}) | "
                      f"µSv/h: {usvh:.4f} ({usvh_min:.4f}, {usvh_avg:.4f}, {usvh_max:.4f})")
                
                # --- PUBLISH TO MQTT (if interval elapsed) ---
                current_time = time.time()
                if client and (current_time - last_publish_time) >= MQTT_PUBLISH_INTERVAL:
                    publish_sensor(client, MQTT_TOPIC_CPM, cpm, cpm_min, cpm_avg, cpm_max)
                    publish_sensor(client, MQTT_TOPIC_USVH, usvh, usvh_min, usvh_avg, usvh_max)
                    last_publish_time = current_time
            else:
                logging.info("CPM: no response")

            time.sleep(1)  # Read every second

    except KeyboardInterrupt:
        logging.info("\nInterrupted by user")
    finally:
        ser.close()
        logging.info("Serial port closed")
        if client:
            client.loop_stop()
            client.disconnect()
            logging.info("Disconnected from MQTT")

if __name__ == "__main__":
    main()
