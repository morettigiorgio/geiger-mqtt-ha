# Geiger Detector MQTT Integration

A complete Docker container solution for interfacing with GQ Electronics GMC Geiger counters (e.g., GMC-500+Re, GMC-600+) over serial connection, publishing radiation measurements to MQTT with Home Assistant discovery support.

## Features

- **Serial Communication**: Read CPM and dose rate data from GMC Geiger detectors via RFC1801 protocol
- **MQTT Publishing**: Publish readings in JSON format with min/avg/max statistics
- **Home Assistant Discovery**: Automatic sensor discovery for seamless HA integration
- **Real-time Statistics**: Track minimum, average, and maximum values over configurable time windows
- **Data Validation**: Automatic filtering of serial noise and anomalous readings
- **Environment Parametrization**: All settings configurable via environment variables
- **Authentication Support**: Optional MQTT username/password authentication

## Project Structure

```
geiger/
├── .gitignore             # Git ignore rules
├── .github-template       # GitHub setup guide
├── LICENSE                # MIT License
├── README.md              # This file
├── Dockerfile             # Container definition
├── docker-compose.yaml    # Docker Compose configuration
├── screenshots/           # Integration examples
└── app/
    ├── main.py            # Main reader and MQTT publisher
    ├── discovery.py       # Home Assistant MQTT discovery publisher
    └── requirements.txt   # Python dependencies
```

## Hardware Requirements

- GQ Electronics GMC Geiger counter (GMC-500+Re, GMC-600+, etc.)
- USB cable
- Network access to MQTT broker
- Docker host with USB passthrough capability

## Building the Container

### Prerequisites

**If using Docker (Recommended):** No prerequisites needed - all dependencies are included in the container.

**If developing/testing locally:** Install Python dependencies:
```bash
pip install -r app/requirements.txt
```

Dependencies:
- `pyserial` - Serial port communication
- `paho-mqtt` - MQTT client library

### Build from Dockerfile

```bash
cd /home/server/docker/data/geiger
docker build -t geiger-detector:latest .
```

## Running the Container

### Docker Run

```bash
docker run -d \
  --name geiger_detector \
  --device=/dev/ttyUSB1:/dev/ttyUSB1 \
  -e MQTT_BROKER=192.168.x.x \
  -e MQTT_PORT=1883 \
  -e MQTT_USER=mosquitto_user \
  -e MQTT_PASSWORD=mosquitto_pass \
  -e DEVICE_ID=geiger-detector \
  -e DEVICE_NAME="Geiger Detector" \
  geiger-detector:latest
```

### Docker Compose

```yaml
services:
  geiger:
    build: ./docker/data/geiger
    container_name: geiger_gmc500
    devices:
      - /dev/ttyUSB1:/dev/ttyUSB1
    environment:
      # Serial Configuration
      SERIAL_PORT: /dev/ttyUSB1
      SERIAL_BAUDRATE: "115200"
      SERIAL_TIMEOUT: "1"
      
      # Geiger Configuration
      CPM_TO_USVH: "153.0"
      WINDOW_SIZE: "10"
      
      # MQTT Configuration
      MQTT_BROKER: mosquitto
      MQTT_PORT: "1883"
      MQTT_USER: mosquitto_user
      MQTT_PASSWORD: mosquitto_pass
      MQTT_TOPIC_CPM: geiger/cpm
      MQTT_TOPIC_USVH: geiger/usvh
      MQTT_CLIENT_ID: geiger-detector
      
      # Home Assistant Discovery
      HA_DISCOVERY_PREFIX: homeassistant
      
      # Device Configuration
      DEVICE_ID: geiger-detector
      DEVICE_NAME: Geiger Detector
      DEVICE_MANUFACTURER: GQ Electronics
      DEVICE_MODEL: GMC-500+
    restart: unless-stopped
    depends_on:
      - mosquitto
    networks:
      - smarthome
```

### Starting and Updating the Container

```bash
# First time: build image and start container
docker compose up -d --build geiger

# Update environment variables or docker-compose.yaml (no Dockerfile changes)
docker compose up -d geiger

# Quick restart (no changes to config/Dockerfile)
docker compose restart geiger

# Rebuild if Dockerfile was modified
docker compose up -d --build geiger

# Complete recreation (clean restart)
docker compose down geiger && docker compose up -d geiger
```

## Environment Variables

### Serial Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SERIAL_PORT` | `/dev/ttyUSB1` | Serial port device path |
| `SERIAL_BAUDRATE` | `115200` | Serial communication speed |
| `SERIAL_TIMEOUT` | `1` | Serial read timeout in seconds |

### Geiger Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CPM_TO_USVH` | `153.0` | Conversion factor (CPM to µSv/h) - GQ SBM-20 constant |
| `WINDOW_SIZE` | `10` | Number of samples for min/avg/max calculation |
| `MAX_CPM` | `100000` | Maximum reasonable CPM value - readings above this are discarded as noise |
| `MAX_CPM_JUMP` | `5.0` | Maximum multiplier for rate of change (e.g., 5.0 = 5x jump is OK, >5x discarded) |

### MQTT Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MQTT_BROKER` | `localhost` | MQTT broker hostname or IP |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `MQTT_USER` | `` (empty) | MQTT username (optional) |
| `MQTT_PASSWORD` | `` (empty) | MQTT password (optional) |
| `MQTT_TOPIC_CPM` | `geiger/cpm` | Topic for CPM readings |
| `MQTT_TOPIC_USVH` | `geiger/usvh` | Topic for µSv/h readings |
| `MQTT_CLIENT_ID` | `geiger-detector` | MQTT client identifier |

### Home Assistant Discovery

| Variable | Default | Description |
|----------|---------|-------------|
| `HA_DISCOVERY_PREFIX` | `homeassistant` | MQTT discovery prefix (must match HA config) |

### Device Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEVICE_ID` | `geiger-detector` | Unique device identifier |
| `DEVICE_NAME` | `Geiger Detector` | Display name in Home Assistant |
| `DEVICE_MANUFACTURER` | `GQ Electronics` | Manufacturer name |
| `DEVICE_MODEL` | `GMC` | Device model name |

## MQTT Topics and Payload

### CPM Reading (geiger/cpm)

```json
{
  "value": 42,
  "min": 40,
  "avg": 41.5,
  "max": 45
}
```

### Dose Rate Reading (geiger/usvh)

```json
{
  "value": 0.2745,
  "min": 0.2614,
  "avg": 0.2713,
  "max": 0.2941
}
```

**Update Frequency**: Every 1 second

## Home Assistant Integration

### Automatic Discovery

The container publishes Home Assistant MQTT Discovery messages on startup:

- **CPM Sensor**: `homeassistant/sensor/geiger-detector-cpm/config`
- **Dose Rate Sensor**: `homeassistant/sensor/geiger-detector-dose_rate/config`

![Home Assistant Integration](screenshots/Screenshot%202026-01-17%20231007.png)

### Manual Configuration (if discovery doesn't work)

Add to your `configuration.yaml`:

```yaml
mqtt:
  broker: 192.168.x.x
  username: mosquitto_user
  password: mosquitto_pass
  discovery: true
  discovery_prefix: homeassistant

sensor:
  - platform: mqtt
    name: "Geiger CPM"
    unique_id: geiger-detector_cpm
    state_topic: geiger/cpm
    unit_of_measurement: "CPM"
    device_class: radiation
    value_template: "{{ value_json.value | int }}"
    json_attributes_topic: geiger/cpm
    icon: mdi:radioactive

  - platform: mqtt
    name: "Geiger Dose Rate"
    unique_id: geiger-detector_dose_rate
    state_topic: geiger/usvh
    unit_of_measurement: "µSv/h"
    device_class: radiation
    value_template: "{{ value_json.value | float }}"
    json_attributes_topic: geiger/usvh
    icon: mdi:nuke
```

Then restart Home Assistant:

```
Settings > System > Restart Home Assistant
```

## Available Scripts

### main.py

Main application that:
- Connects to the Geiger detector via serial (native USB connection)
- Reads CPM and calculates µSv/h
- Tracks min/avg/max statistics
- Publishes to MQTT every second

### discovery.py

Publishes Home Assistant MQTT Discovery messages to enable automatic device and sensor discovery.

```bash
python3 /app/discovery.py
```

## Troubleshooting

### Container Won't Start

1. Check serial port exists:
   ```bash
   ls -la /dev/ttyUSB*
   ```

2. Check container logs:
   ```bash
   docker logs -f geiger_gmc500
   ```

3. Verify device permissions:
   ```bash
   docker run --device=/dev/ttyUSB1:/dev/ttyUSB1 --rm geiger-detector:latest ls -la /dev/ttyUSB1
   ```

### No MQTT Connection

1. Check MQTT broker is running:
   ```bash
   docker logs mosquitto
   ```

2. Verify credentials:
   ```bash
   mosquitto_pub -h 192.168.x.x -u mosquitto_user -P mosquitto_pass -t test -m "hello"
   ```

### Sensor Not Appearing in Home Assistant

1. Verify Home Assistant MQTT integration is enabled:
   - Settings > Devices and Services > MQTT
   - Should show "Connected to {MQTT_BROKER}"

2. Check MQTT discovery is enabled in Home Assistant `configuration.yaml`:
   ```yaml
   mqtt:
     discovery: true
     discovery_prefix: homeassistant
   ```

3. Restart Home Assistant:
   - Settings > System > Restart Home Assistant

4. Check discovery topic in MQTT:
   ```bash
   mosquitto_sub -h 192.168.x.x -u user -P pass \
     -t "homeassistant/sensor/geiger-detector-cpm/config" \
     -v
   ```

### No Data in MQTT

1. Check serial connection:
   ```bash
   docker exec -it geiger_gmc500 bash
   cat /dev/ttyUSB1 &
   # Should see binary data from detector
   ```

2. Check MQTT messages:
   ```bash
   mosquitto_sub -h 192.168.x.x -u user -P pass \
     -t "geiger/#" -v
   ```

3. Check container logs for errors:
   ```bash
   docker logs -f geiger_gmc500
   ```

### Discarded Readings / Noise Filtering

If you see `[WARN] Discarded invalid CPM reading:` in logs, the validation filter is working. This happens when:

1. **Serial noise**: Corrupted data from serial connection
2. **Extreme values**: CPM reading exceeds `MAX_CPM` (default 100000)
3. **Rate spikes**: Value jumps >5x from previous reading

To adjust filtering:

```yaml
environment:
  MAX_CPM: "50000"          # Lower limit for valid readings
  MAX_CPM_JUMP: "3.0"       # Stricter jump tolerance (3x instead of 5x)
```

If legitimate readings are being discarded, increase these values:

```yaml
environment:
  MAX_CPM: "500000"         # Higher if detector is very close to source
  MAX_CPM_JUMP: "10.0"      # Allow larger jumps
```

### High/Low Readings

- Verify `CPM_TO_USVH` conversion factor matches your detector model:
  - GMC-500+Re: 153.0 CPM/µSv/h
  - GMC-600+: ~133.0 CPM/µSv/h
  - Refer to manufacturer documentation

## GMC Detector Models and Conversion Factors

| Model | CPM_TO_USVH | Notes |
|-------|------------|-------|
| GMC-500+Re | 153.0 | Standard SBM-20 tube |
| GMC-600+ | 133.0 | Dual tube detector |
| GMC-300 | 153.0 | Older SBM-20 model |
| GMC-320 | 153.0 | SBM-20 tube |

Check your detector documentation or calibration sheet for the correct value.

## Docker Compose Full Example

```yaml
version: '3.8'

services:
  mosquitto:
    image: eclipse-mosquitto:latest
    container_name: mosquitto
    ports:
      - "1883:1883"
    volumes:
      - ./mosquitto/config:/mosquitto/config
      - ./mosquitto/data:/mosquitto/data
      - ./mosquitto/log:/mosquitto/log
    networks:
      - smarthome
    restart: unless-stopped

  geiger:
    build: ./docker/data/geiger
    container_name: geiger_gmc500
    devices:
      - /dev/ttyUSB1:/dev/ttyUSB1
    environment:
      SERIAL_PORT: /dev/ttyUSB1
      SERIAL_BAUDRATE: "115200"
      CPM_TO_USVH: "153.0"
      WINDOW_SIZE: "10"
      MQTT_BROKER: mosquitto
      MQTT_PORT: "1883"
      MQTT_USER: geiger_user
      MQTT_PASSWORD: geiger_pass
      DEVICE_ID: geiger-detector
      DEVICE_NAME: "GMC-500+ Geiger Counter"
      DEVICE_MANUFACTURER: "GQ Electronics"
      DEVICE_MODEL: "GMC-500+Re"
    depends_on:
      - mosquitto
    networks:
      - smarthome
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

networks:
  smarthome:
    driver: bridge
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## GitHub Publication

Ready to publish? Follow the steps in [.github-template](.github-template):

```bash
git init
git add .
git commit -m "Initial commit: Geiger detector MQTT integration"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/geiger-mqtt-ha.git
git push -u origin main
```

Recommended repository metadata:
- **Description**: GQ Electronics GMC Geiger detector MQTT integration with Home Assistant discovery
- **Topics**: `geiger-detector`, `mqtt`, `home-assistant`, `iot`, `python`
- **License**: MIT

## Support

For issues related to:
- **MQTT/Home Assistant**: Check MQTT broker logs and HA integration
- **Serial Communication**: Verify USB connection and port permissions
- **Geiger Readings**: Consult detector manual for calibration and conversion factors
- **Container Runtime**: Check Docker logs with `docker logs -f geiger_gmc500`

## References

- [GQ RFC1801 Protocol Specification](https://www.gqelectronicsllc.com/download/GQ-RFC1801.txt) - Serial communication protocol for GMC detectors
- [GQ Electronics GMC Protocol Manual](https://www.gqelectronicsllc.com/comersus/store/products/GMC-500Plus-Kit/Manual%20V5.24.pdf)
- [Home Assistant MQTT Integration](https://www.home-assistant.io/integrations/mqtt/)
- [Home Assistant MQTT Discovery](https://www.home-assistant.io/docs/mqtt/discovery/)
- [Paho MQTT Python Client](https://github.com/eclipse/paho.mqtt.python)
