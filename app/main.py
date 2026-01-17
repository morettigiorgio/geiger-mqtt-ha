import serial
import time
import struct
from collections import deque

PORT = "/dev/ttyUSB1"
BAUDRATE = 115200
TIMEOUT = 1

CPM_TO_USVH = 153.0  # costante GQ per SBM-20
WINDOW_SIZE = 10  # numero di campioni per la media

def send_cmd(ser, cmd, resp_len=0, is_ascii=False):
    """
    Invia comando RFC1801 al GMC e legge risposta.
    - cmd: stringa comando (es. 'GETVER')
    - resp_len: numero di byte attesi (0 = nessuna lettura)
    - is_ascii: se True decodifica in ASCII
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
    Per comandi RFC1801 che ritornano ASCII di lunghezza variabile,
    leggiamo fino a timeout o fino a '>>' (indicatore di fine pacchetto).
    """
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

def main():
    ser = serial.Serial(PORT, BAUDRATE, timeout=TIMEOUT)
    try:
        print(f"Connesso a {PORT} @ {BAUDRATE}")
        time.sleep(0.5)

        # --- DISATTIVA HEARTBEAT ---
        print("Disabilito heartbeat (HEARTBEAT0)")
        send_cmd(ser, "HEARTBEAT0")

        # --- VERSIONE ASCII ---
        version = read_variable_ascii(ser, "GETVER", timeout=1.5)
        print("Versione:", version if version else "<nessuna risposta>")

        # --- BATTERIA ASCII (5 byte) ---
        batt = send_cmd(ser, "GETVOLT", resp_len=5, is_ascii=True)
        print("Battery:", batt if batt else "<nessuna risposta>")

        # --- SERIAL NUMBER (7 byte) ---
        raw_ser = send_cmd(ser, "GETSERIAL", resp_len=7)
        if raw_ser:
            serial_num = raw_ser.hex().upper()
            print("Serial:", serial_num)
        else:
            print("Serial: nessuna risposta")

        # --- DATETIME (7 byte) ---
        raw_dt = send_cmd(ser, "GETDATETIME", resp_len=7)
        if raw_dt:
            yy, mm, dd, hh, mi, ss, aa = raw_dt
            print(f"Data/Ora: 20{yy:02d}-{mm:02d}-{dd:02d} {hh:02d}:{mi:02d}:{ss:02d}")
        else:
            print("Data/Ora: nessuna risposta")

        print("\nInizio lettura continua (Ctrl+C per uscire)...\n")

        # --- BUFFER PER PICCO E MEDIA ---
        cpm_history = deque(maxlen=WINDOW_SIZE)
        usvh_history = deque(maxlen=WINDOW_SIZE)

        # --- LOOP CONTINUO ---
        while True:
            # --- CPM (4 byte big endian) ---
            raw_cpm = send_cmd(ser, "GETCPM", resp_len=4)
            if raw_cpm:
                cpm = struct.unpack(">I", raw_cpm)[0]
                # µSv/h CALCOLATO
                usvh = round(cpm / CPM_TO_USVH, 4)
                
                # Aggiungi ai buffer storici
                cpm_history.append(cpm)
                usvh_history.append(usvh)
                
                # Calcola minimo, media e massimo
                cpm_min = min(cpm_history) if cpm_history else 0
                cpm_avg = round(sum(cpm_history) / len(cpm_history), 2) if cpm_history else 0
                cpm_max = max(cpm_history) if cpm_history else 0
                usvh_min = round(min(usvh_history), 4) if usvh_history else 0
                usvh_avg = round(sum(usvh_history) / len(usvh_history), 4) if usvh_history else 0
                usvh_max = round(max(usvh_history), 4) if usvh_history else 0
                
                print(f"CPM: {cpm:6d} ({cpm_min:6d}, {cpm_avg:6.2f}, {cpm_max:6d}) | "
                      f"µSv/h: {usvh:.4f} ({usvh_min:.4f}, {usvh_avg:.4f}, {usvh_max:.4f})")
            else:
                print("CPM: nessuna risposta")

            time.sleep(1)  # Leggi ogni secondo

    except KeyboardInterrupt:
        print("\nInterrotto dall'utente")
    finally:
        ser.close()
        print("Porta seriale chiusa")

if __name__ == "__main__":
    main()
