import paho.mqtt.client as mqtt
import json
import os
import time

# --- MQTT CONFIGURATION ---
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "geiger-detector")

# Home Assistant Discovery
HA_DISCOVERY_TOPIC_PREFIX = os.getenv("HA_DISCOVERY_PREFIX", "homeassistant")

# --- DEVICE CONFIGURATION ---
DEVICE_ID = os.getenv("DEVICE_ID", "geiger-detector")
DEVICE_NAME = os.getenv("DEVICE_NAME", "Geiger Detector")
DEVICE_MANUFACTURER = os.getenv("DEVICE_MANUFACTURER", "GQ Electronics")
DEVICE_MODEL = os.getenv("DEVICE_MODEL", "GMC")

def on_connect(client, userdata, flags, rc, *args, **kwargs):
    """MQTT connection callback"""
    if rc == 0:
        print("[Discovery] Connected to MQTT broker")
    else:
        print(f"[Discovery] Connection error, code: {rc}")

def on_disconnect(client, userdata, rc, *args, **kwargs):
    """MQTT disconnection callback"""
    # Only print if it's a real error (rc != 0 and not a normal client-initiated disconnect)
    if rc != 0 and not str(rc).startswith("DisconnectFlags"):
        print(f"[Discovery] Unexpected disconnection, code: {rc}")

def publish_discovery(client):
    """Publish discovery messages for Home Assistant"""
    device_info = {
        "identifiers": [DEVICE_ID],
        "name": DEVICE_NAME,
        "manufacturer": DEVICE_MANUFACTURER,
        "model": DEVICE_MODEL,
        "hw_version": "1.0",
        "sw_version": "1.0"
    }
    
    # --- SENSOR CPM ---
    cpm_discovery = {
        "unique_id": f"{DEVICE_ID}_cpm",
        "icon": "mdi:radioactive",
        "name": "CPM",
        "state_topic": "geiger/cpm",
        "unit_of_measurement": "CPM",
        "state_class": "measurement",
        "value_template": "{{ value_json.value | int }}",
        "json_attributes_topic": "geiger/cpm",
        "json_attributes_template": "{{ value_json | tojson }}",
        "device": device_info,
        "platform": "mqtt"
    }
    
    cpm_topic = f"{HA_DISCOVERY_TOPIC_PREFIX}/sensor/{DEVICE_ID}-cpm/config"
    client.publish(cpm_topic, json.dumps(cpm_discovery), qos=1, retain=True)
    print(f"[Discovery] Published CPM to: {cpm_topic}")
    
    # --- SENSOR uSv/h ---
    usvh_discovery = {
        "unique_id": f"{DEVICE_ID}_dose_rate",
        "icon": "mdi:nuke",
        "name": "Dose Rate",
        "state_topic": "geiger/usvh",
        "unit_of_measurement": "uSv/h",
        "state_class": "measurement",
        "value_template": "{{ value_json.value | float }}",
        "json_attributes_topic": "geiger/usvh",
        "json_attributes_template": "{{ value_json | tojson }}",
        "device": device_info,
        "platform": "mqtt"
    }

    usvh_topic = f"{HA_DISCOVERY_TOPIC_PREFIX}/sensor/{DEVICE_ID}-dose_rate/config"
    client.publish(usvh_topic, json.dumps(usvh_discovery), qos=1, retain=True)
    print(f"[Discovery] Published Dose Rate to: {usvh_topic}")
    
    # --- SWITCH SPEAKER ---
    speaker_discovery = {
        "unique_id": f"{DEVICE_ID}_speaker",
        "icon": "mdi:volume-high",
        "name": "Speaker",
        "state_topic": "geiger/speaker/state",
        "command_topic": "geiger/speaker/set",
        "state_on": "ON",
        "state_off": "OFF",
        "payload_on": "on",
        "payload_off": "off",
        "entity_category": "config",
        "device": device_info,
        "platform": "mqtt"
    }
    
    speaker_topic = f"{HA_DISCOVERY_TOPIC_PREFIX}/switch/{DEVICE_ID}-speaker/config"
    client.publish(speaker_topic, json.dumps(speaker_discovery), qos=1, retain=True)
    print(f"[Discovery] Published Speaker switch to: {speaker_topic}")

def main():
    # Try VERSION2 first, fallback to default for older paho-mqtt versions
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{MQTT_CLIENT_ID}-discovery")
    except (AttributeError, TypeError):
        client = mqtt.Client(client_id=f"{MQTT_CLIENT_ID}-discovery")
    
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    
    try:
        if MQTT_USER and MQTT_PASSWORD:
            client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
        
        print(f"[Discovery] Connecting to {MQTT_BROKER}:{MQTT_PORT}...")
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        
        time.sleep(2)
        publish_discovery(client)
        time.sleep(1)
        
        client.loop_stop()
        client.disconnect()
        print("[Discovery] Discovery complete!")
        
    except Exception as e:
        print(f"[Discovery] Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())