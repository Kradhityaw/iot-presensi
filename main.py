# ==========================================================
# FINAL CODE: SISTEM ABSENSI RFID DENGAN ESP32 & SUPABASE
# Versi: 4.3 (Final Clean Up & Bug Fixes)
# ==========================================================
import network
import urequests
import time
import json
from machine import Pin, SPI, PWM, I2C
from mfrc522 import MFRC522
from ssd1306 import SSD1306_I2C
import ntptime

# --- KONFIGURASI ---
WIFI_SSID = "kvnd"
WIFI_PASSWORD = "00000000"
SUPABASE_URL = "https://oxkuxwkehinhyxfsauqe.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im94a3V4d2tlaGluaHl4ZnNhdXFlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTc5NDYxOTMsImV4cCI6MjA3MzUyMjE5M30.g3BjGtZCSFxnBDwMWkaM2mEcnCkoDL92fvTP_gUgR20"
DEVICE_ID = 1
PIN_RFID_CS = 5; PIN_RFID_SCK = 18; PIN_RFID_MOSI = 23; PIN_RFID_MISO = 19; PIN_RFID_RST = 4
PIN_BUZZER = 15
PIN_I2C_SCL = 22
PIN_I2C_SDA = 21
OLED_I2C_ADDR = 0x3C
_VERSION=4.3

# --- PENGATURAN PERILAKU ---
IDLE_TIMEOUT_SECONDS = 15
DEBOUNCE_DELAY_SECONDS = 5
OLED_MESSAGE_DURATION_SECONDS = 0

# --- VARIABEL GLOBAL ---
rfid_cache = {}
attendance_queue = []
last_tap_time = 0
last_card_uid = None
last_read_time = 0
oled_is_showing_welcome = True # <-- DIKEMBALIKAN

# --- INISIALISASI PERANGKAT KERAS ---
i2c = I2C(0, scl=Pin(PIN_I2C_SCL), sda=Pin(PIN_I2C_SDA))
oled = SSD1306_I2C(128, 64, i2c, OLED_I2C_ADDR)
spi = SPI(2, baudrate=2500000, polarity=0, phase=0)
spi.init(sck=Pin(PIN_RFID_SCK), mosi=Pin(PIN_RFID_MOSI), miso=Pin(PIN_RFID_MISO))
rdr = MFRC522(spi=spi, gpioRst=Pin(PIN_RFID_RST, Pin.OUT), gpioCs=Pin(PIN_RFID_CS, Pin.OUT))
buzzer = PWM(Pin(PIN_BUZZER)); buzzer.freq(300000)

# --- FUNGSI TAMPILAN OLED ---
def oled_show(line1, line2="", line3=""):
    oled.fill(0); oled.text(line1, 0, 5); oled.text(line2, 0, 25); oled.text(line3, 0, 45); oled.show()

# --- FUNGSI NADA KUSTOM (LENGKAP) ---
def siapDigunakan(): buzzer.freq(1047); time.sleep(0.12); buzzer.freq(1175); time.sleep(0.12); buzzer.freq(1319); time.sleep(0.12); buzzer.freq(300000)
def muat(): buzzer.freq(523); time.sleep(0.2); buzzer.freq(659); time.sleep(0.2); buzzer.freq(784); time.sleep(0.15); buzzer.freq(300000)
def scan(): buzzer.freq(1500); time.sleep(0.15); buzzer.freq(300000)
def success(): buzzer.freq(2000); time.sleep(0.05); buzzer.freq(3000); time.sleep(0.05); buzzer.freq(3500); time.sleep(0.1); buzzer.freq(300000)
def danger(): buzzer.freq(500); time.sleep(0.2); buzzer.freq(30000); time.sleep(0.1); buzzer.freq(500); time.sleep(0.2); buzzer.freq(30000); time.sleep(0.1); buzzer.freq(500); time.sleep(0.2); buzzer.freq(30000)
def warning(): buzzer.freq(800); time.sleep(0.1); buzzer.freq(30000); time.sleep(0.1); buzzer.freq(800); time.sleep(0.1); buzzer.freq(30000)
    
# --- FUNGSI KONEKTIVITAS & SINKRONISASI ---
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print('Menghubungkan ke WiFi...'); wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        while not wlan.isconnected(): time.sleep(1)
    print('Koneksi WiFi Berhasil!', wlan.ifconfig())
    return True

def sync_time():
    print("Sinkronisasi waktu...");
    try: ntptime.settime(); print("Waktu berhasil disinkronkan.")
    except Exception: print("Gagal sinkronisasi waktu.")
        
def sync_rfid_cache():
    """Mengunduh UID kartu BESERTA NAMA PENGGUNA dan menyimpannya di cache."""
    global rfid_cache
    print("Mulai sinkronisasi cache RFID & Nama...")
    oled_show("Sinkronisasi", "Data...")
    
    # Query join untuk mengambil nama dari user_profiles
    query = "card_number,organization_member_id,organization_members(user_profiles(first_name))"
    url = f"{SUPABASE_URL}/rest/v1/rfid_cards?select={query}"
    headers = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'}
    
    try:
        response = urequests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            rfid_cache = {}
            for item in data:
                # Ambil nama dari data JSON yang nested
                try:
                    name = item['organization_members']['user_profiles']['first_name']
                except (TypeError, KeyError):
                    name = "ErrorNama" # Fallback jika data nama tidak lengkap
                
                rfid_cache[item['card_number']] = {
                    'member_id': item['organization_member_id'],
                    'name': name
                }
            print(f"Sinkronisasi berhasil! {len(rfid_cache)} kartu & nama dimuat.")
            muat()
        response.close()
    except Exception as e:
        print(f"Error sinkronisasi cache: {e}")
        danger()

def upload_attendance_batch():
    global attendance_queue
    if not attendance_queue: return
    print(f"\n--- Mode Upload ---")
    print(f"Mengirim {len(attendance_queue)} data absensi...")
    url = f"{SUPABASE_URL}/rest/v1/rpc/handle_attendance_batch"
    headers = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}', 'Content-Type': 'application/json'}
    payload = {'taps': attendance_queue}
    try:
        response = urequests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code == 200 and 'BATCH_PROCESSED' in response.text:
            print("Upload batch berhasil!"); success()
            attendance_queue = []
        else:
            print(f"Upload batch gagal. Status: {response.status_code}, Pesan: {response.text}"); danger()
        response.close()
    except Exception as e:
        print(f"Error saat upload batch: {e}"); danger()

# --- PROGRAM UTAMA ---
oled_show("Sistem Absensi", "Inisialisasi...")
if connect_wifi():
    sync_time()
    sync_rfid_cache()
else:
    oled_show("Error", "Gagal WiFi"); danger()

print(f"\n===== Sistem Absensi Siap (v{_VERSION}) =====")
oled_show("Letakkan Kartu", "Anda...")
siapDigunakan()
last_tap_time = time.time()
oled_is_showing_welcome = True

# --- LOOP UTAMA ---
while True:
    # --- Blok 1: Deteksi Idle (Untuk Upload & Reset Tampilan OLED) ---
    if time.time() - last_tap_time > IDLE_TIMEOUT_SECONDS:
        if attendance_queue:
            oled_show("Mengirim Data", "Ke Server...")
            upload_attendance_batch()
        if not oled_is_showing_welcome:
            print("\nSesi absensi selesai, kembali ke mode siaga.")
            oled_show("Letakkan Kartu", "Anda...")
            oled_is_showing_welcome = True
        last_tap_time = time.time()
        
    # --- Blok 2: Pembacaan Kartu ---
    uid = rdr.read_uid()
    if uid:
        current_read_time = time.time()
        uid_str = "".join(["{:02x}".format(x) for x in uid[0:4]])
        
        if not (uid_str == last_card_uid and current_read_time - last_read_time < DEBOUNCE_DELAY_SECONDS):
            last_card_uid = uid_str
            last_read_time = current_read_time
            scan()
            time.sleep(0.1)
            success()
            
            if uid_str in rfid_cache:
                user_data = rfid_cache[uid_str]
                name = user_data['name']
                oled_show("Selamat Datang", name)
                member_id = user_data['member_id']
                current_time_tuple = time.localtime()
                timestamp_str = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(*current_time_tuple[0:6])
                attendance_queue.append({'member_id_input': member_id, 'event_time_input': timestamp_str})
                print(f"Antrean: {len(attendance_queue)} | Kartu OK: {name} ({uid_str})")
            else:
                oled_show("Kartu Ditolak", "Tidak Terdaftar")
                print(f"Kartu Ditolak: {uid_str}")
                warning()

            last_tap_time = time.time()
            oled_is_showing_welcome = False
            time.sleep(OLED_MESSAGE_DURATION_SECONDS) # <-- DIKEMBALIKAN
            
    time.sleep_ms(50)