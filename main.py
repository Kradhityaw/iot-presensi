# ==========================================================
# FINAL CODE: SISTEM ABSENSI RFID DENGAN ESP32 & SUPABASE
# Versi: 4.3 (Final Clean Up & Non-Blocking OLED)
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
DEVICE_ID = 2 # ID unik untuk mesin ini
_VERSION = "4.3" # Versi software

# --- PENGATURAN PIN ---
PIN_RFID_CS = 5; PIN_RFID_SCK = 18; PIN_RFID_MOSI = 23; PIN_RFID_MISO = 19; PIN_RFID_RST = 4
PIN_BUZZER = 15
PIN_I2C_SCL = 22
PIN_I2C_SDA = 21
OLED_I2C_ADDR = 0x3C

# --- PENGATURAN PERILAKU ---
IDLE_TIMEOUT_SECONDS = 15
DEBOUNCE_DELAY_SECONDS = 5
OLED_MESSAGE_DURATION_MS = 3000 # Durasi pesan di OLED dalam milidetik

# --- VARIABEL GLOBAL ---
rfid_cache = {}
attendance_queue = []
last_tap_time = 0
last_card_uid = None
last_read_time = 0
oled_message_timer = 0
oled_is_displaying_message = False

# --- INISIALISASI PERANGKAT KERAS ---
i2c = I2C(0, scl=Pin(PIN_I2C_SCL), sda=Pin(PIN_I2C_SDA))
oled = SSD1306_I2C(128, 64, i2c, OLED_I2C_ADDR)
spi = SPI(2, baudrate=2500000, polarity=0, phase=0)
spi.init(sck=Pin(PIN_RFID_SCK), mosi=Pin(PIN_RFID_MOSI), miso=Pin(PIN_RFID_MISO))
rdr = MFRC522(spi=spi, gpioRst=Pin(PIN_RFID_RST, Pin.OUT), gpioCs=Pin(PIN_RFID_CS, Pin.OUT))
buzzer = PWM(Pin(PIN_BUZZER)); buzzer.freq(300000)

# --- FUNGSI TAMPILAN OLED ---
def oled_show(line1, line2="", line3="", line4=""):
    oled.fill(0)
    oled.text(line1, 0, 0)
    oled.text(line2, 0, 16)
    oled.text(line3, 0, 32)
    oled.text(line4, 0, 48)
    oled.show()

def oled_center_multiline(lines):
    oled.fill(0)
    num_lines = len(lines); line_height = 10; total_text_height = num_lines * line_height
    y_start = (64 - total_text_height) // 2
    for i, line in enumerate(lines):
        x = (128 - len(line) * 8) // 2
        y = y_start + (i * line_height)
        oled.text(line, x, y)
    oled.show()
    
def oled_wrap_center(text):
    """
    Menampilkan teks panjang di tengah layar, dengan fitur word-wrap otomatis.
    """
    oled.fill(0) # Selalu bersihkan layar

    # Pengaturan font dan layar
    char_width = 8
    screen_width = 128
    line_height = 10 # Jarak vertikal antar baris

    # --- Langkah 1: Word Wrapping ---
    # Pecah teks menjadi beberapa baris yang tidak melebihi lebar layar
    words = text.split(' ')
    lines = []
    current_line = ""
    for word in words:
        if len(current_line) + len(word) + 1 > (screen_width // char_width):
            lines.append(current_line)
            current_line = word
        else:
            if current_line:
                current_line += " " + word
            else:
                current_line = word
    lines.append(current_line)

    # --- Langkah 2: Centering ---
    # Hitung posisi y (vertikal) awal agar seluruh blok teks di tengah
    num_lines = len(lines)
    total_text_height = (num_lines - 1) * line_height + 8
    y_start = (64 - total_text_height) // 2

    # --- Langkah 3: Tampilkan Setiap Baris ---
    for i, line in enumerate(lines):
        # Hitung posisi x (horizontal) untuk SETIAP baris agar rata tengah
        x = (screen_width - len(line) * char_width) // 2
        y = y_start + (i * line_height)
        oled.text(line, x, y)
        
    oled.show()

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
    oled_wrap_center("Sync Data To Server...")
    
    # Query join untuk mengambil nama dari user_profiles
    query = "card_number,organization_member_id,organization_members(user_profiles(first_name,last_name))"
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
                    name = f"{item['organization_members']['user_profiles']['first_name']} {item['organization_members']['user_profiles']['last_name']}"
                except (TypeError, KeyError):
                    name = "ErrorNama" # Fallback jika data nama tidak lengkap
                
                rfid_cache[item['card_number']] = {
                    'member_id': item['organization_member_id'],
                    'name': name
                }
            print(f"Sinkronisasi berhasil! {len(rfid_cache)} kartu & nama dimuat.")
            oled_center_multiline([
                "",
                "Sync Data To",
                "Server...",
                "",
                "Success",
                ""
                ])
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
            oled_center_multiline([
                                    "",
                                    "Send Data To",
                                    "Server...",
                                    "",
                                    "Success",
                                    ""
                                    ])
            time.sleep(1)
            attendance_queue = []
        else:
            print(f"Upload batch gagal. Status: {response.status_code}, Pesan: {response.text}"); danger()
        response.close()
    except Exception as e:
        print(f"Error saat upload batch: {e}"); danger()

# --- PROGRAM UTAMA ---
# 1. Tampilkan Layar Booting
lines_to_show = ["",
                 "Presence Machine",
                 "By", "PT Universal",
                 "Big Data",
                 ""]
oled_center_multiline(lines_to_show)
time.sleep(2.0)

lines_to_show = ["",
                 "Ver: 3.4",
                 "---------------",
                 "SN: 028192812",
                 ""]
oled_center_multiline(lines_to_show)
time.sleep(2.0)

oled_wrap_center("PT Jaya Abadi Aman Jaya Super Aman")
time.sleep(2.0)

# 2. Inisialisasi Koneksi
oled_wrap_center("initialization Settings....")
if connect_wifi():
    sync_time()
    time.sleep(0.5)
    sync_rfid_cache()
    time.sleep(0.5)
else:
    oled_show("Error", "Gagal WiFi"); danger()

message = [
    "",
    "",
    "Please Scan",
    "Your Card",
    "",
    ""
    ]

# 3. Siap Beroperasi
print(f"\n===== Sistem Absensi Siap (v{_VERSION}) =====")
oled_center_multiline(message)
siapDigunakan()
last_tap_time = time.time()

# --- LOOP UTAMA ---
while True:
    current_millis = time.ticks_ms()

    # Blok 1: Reset Tampilan OLED setelah Timeout (Non-Blocking)
    if oled_is_displaying_message and time.ticks_diff(current_millis, oled_message_timer) > OLED_MESSAGE_DURATION_MS:
        oled_center_multiline(message) # Gunakan fungsi baru
        oled_is_displaying_message = False

    # Blok 2: Deteksi Idle dan Upload
    if time.time() - last_tap_time > IDLE_TIMEOUT_SECONDS:
        if attendance_queue:
            oled_wrap_center("Send Data To Server...") # Gunakan fungsi baru
            upload_attendance_batch()
            oled_center_multiline(message) # Gunakan fungsi baru
            oled_is_displaying_message = False
        last_tap_time = time.time()
        
    # Blok 3: Pembacaan Kartu
    uid = rdr.read_uid()
    if uid:
        uid_str = "".join(["{:02x}".format(x) for x in uid[0:4]])
        
        if not (uid_str == last_card_uid and time.time() - last_read_time < DEBOUNCE_DELAY_SECONDS):
            last_card_uid = uid_str; last_read_time = time.time(); scan(); time.sleep(0.1); success()
            
            if uid_str in rfid_cache:
                user_data = rfid_cache[uid_str]
                name = user_data['name']
                
                # --- PERUBAHAN DI SINI ---
                # Cukup gabungkan teks, fungsi akan menangani sisanya
                oled_wrap_center(f"{name} Success")
                
                # Proses data absensi
                member_id = user_data['member_id']; current_time_tuple = time.localtime()
                timestamp_str = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(*current_time_tuple[0:6])
                attendance_queue.append({'member_id_input': member_id, 'event_time_input': timestamp_str})
                print(f"Antrean: {len(attendance_queue)} | Kartu OK: {name} ({uid_str})")
            else:
                # --- PERUBAHAN DI SINI ---
                oled_wrap_center("Card Declined Not Registered")
                print(f"Kartu Ditolak: {uid_str}"); warning()

            last_tap_time = time.time()
            oled_message_timer = current_millis
            oled_is_displaying_message = True
            
    time.sleep_ms(50)