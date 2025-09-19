# ==========================================================
# FINAL CODE: SISTEM ABSENSI RFID DENGAN ESP32 & SUPABASE
# Versi: 4.4 (Font Vertical Stretch - Besar & Center)
# ==========================================================
import network
import urequests
import time
import json
from machine import Pin, SPI, PWM, I2C
from mfrc522 import MFRC522
from ssd1306 import SSD1306_I2C
import framebuf
import ntptime

# --- TAMBAHAN KONFIGURASI POWER-SAFE ---
MAX_RETRY_UPLOAD = 3
RETRY_DELAY_SECONDS = 2
WIFI_CHECK_TIMEOUT = 10
HTTP_TIMEOUT = 15  # Timeout untuk HTTP request
BATCH_SIZE_LIMIT = 5  # Batasi ukuran batch untuk mengurangi load

# --- KONFIGURASI ---
WIFI_SSID = "kvnd"
WIFI_PASSWORD = "00000000"
SUPABASE_URL = "https://oxkuxwkehinhyxfsauqe.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im94a3V4d2tlaGluaHl4ZnNhdXFlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTc5NDYxOTMsImV4cCI6MjA3MzUyMjE5M30.g3BjGtZCSFxnBDwMWkaM2mEcnCkoDL92fvTP_gUgR20"
DEVICE_ID = 2 # ID unik untuk mesin ini
_VERSION = "4.4" # Versi software dengan font vertical stretch

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

# Variabel untuk data organisasi
organization_name = "Memuat..."
organization_id = 1  # ID organisasi yang digunakan

# --- INISIALISASI PERANGKAT KERAS ---
i2c = I2C(0, scl=Pin(PIN_I2C_SCL), sda=Pin(PIN_I2C_SDA))
oled = SSD1306_I2C(128, 64, i2c, OLED_I2C_ADDR)
spi = SPI(2, baudrate=2500000, polarity=0, phase=0)
spi.init(sck=Pin(PIN_RFID_SCK), mosi=Pin(PIN_RFID_MOSI), miso=Pin(PIN_RFID_MISO))
rdr = MFRC522(spi=spi, gpioRst=Pin(PIN_RFID_RST, Pin.OUT), gpioCs=Pin(PIN_RFID_CS, Pin.OUT))
buzzer = PWM(Pin(PIN_BUZZER)); buzzer.freq(300000)

def check_wifi_strength():
    """Cek kekuatan sinyal WiFi"""
    try:
        wlan = network.WLAN(network.STA_IF)
        if wlan.isconnected():
            # RSSI values: -30 = excellent, -67 = good, -80 = poor
            rssi = wlan.status('rssi') if hasattr(wlan, 'status') else -50
            return rssi > -80  # Return True jika sinyal cukup kuat
        return False
    except:
        return False

def ensure_wifi_connection():
    """Memastikan koneksi WiFi stabil dengan timeout"""
    wlan = network.WLAN(network.STA_IF)
    
    if wlan.isconnected() and check_wifi_strength():
        return True
    
    print("Reconnecting WiFi...")
    oled_center_multiline_vertical_stretch(["Menghubungkan", "WiFi...", "", ""])
    
    try:
        wlan.active(False)
        time.sleep(1)
        wlan.active(True)
        time.sleep(1)
        
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        
        # Wait with timeout
        start_time = time.time()
        while not wlan.isconnected():
            if time.time() - start_time > WIFI_CHECK_TIMEOUT:
                print("WiFi connection timeout")
                return False
            time.sleep(0.5)
        
        # Double check signal strength
        if check_wifi_strength():
            print(f"WiFi reconnected successfully. RSSI: {wlan.status('rssi') if hasattr(wlan, 'status') else 'Unknown'}")
            return True
        else:
            print("WiFi connected but signal too weak")
            return False
            
    except Exception as e:
        print(f"WiFi connection error: {e}")
        return False

# ===== FONT VERTICAL STRETCH FUNCTIONS =====
def draw_char_vertical_stretch(char, x, y):
    """
    Font dengan stretching vertikal - lebar tetap, tinggi 2x
    """
    char_buffer = bytearray(8)
    temp_fb = framebuf.FrameBuffer(char_buffer, 8, 8, framebuf.MONO_HLSB)
    temp_fb.text(char, 0, 0)
    
    for px in range(8):
        for py in range(8):
            if temp_fb.pixel(px, py):
                # Gambar di posisi asli
                oled.pixel(x + px, y + py*2, 1)
                # Tambah pixel vertikal untuk tinggi 2x
                oled.pixel(x + px, y + py*2 + 1, 1)

def tampilkan_font_vertical_stretch_center(teks_list):
    """
    Font vertical stretch dengan center alignment - maksimal 4 baris
    """
    oled.fill(0)
    
    # Maksimal 16 karakter per baris dengan font vertical stretch
    max_char_per_baris = 16
    
    # Posisi Y untuk 4 baris - memenuhi layar penuh (64px)
    posisi_y = [0, 16, 32, 48]  # Tinggi 16px per baris
    
    # Batasi maksimal 4 baris sesuai permintaan
    if len(teks_list) > 4:
        teks_list = teks_list[:4]
    
    for baris_idx, teks in enumerate(teks_list):
        # Potong teks jika terlalu panjang
        if len(teks) > max_char_per_baris:
            teks = teks[:max_char_per_baris-3] + "..."
        
        # CENTER ALIGNMENT - hitung posisi x untuk rata tengah
        teks_length = len(teks)
        x_start = (128 - (teks_length * 8)) // 2  # 8px lebar per karakter
        x_start = max(0, x_start)  # Pastikan tidak negatif
        
        x_pos = x_start
        for char in teks:
            draw_char_vertical_stretch(char, x_pos, posisi_y[baris_idx])
            x_pos += 8  # Lebar normal 8px per karakter
    
    oled.show()

def oled_wrap_center_vertical_stretch(text):
    """
    Menampilkan teks panjang dengan word wrap, center alignment, dan font vertical stretch
    """
    # Pengaturan untuk font vertical stretch
    char_width = 8  # Lebar karakter tetap 8px
    screen_width = 128
    max_char_per_baris = 16
    
    # --- Word Wrapping ---
    words = text.split(' ')
    lines = []
    current_line = ""
    
    for word in words:
        # Cek apakah menambah word akan melebihi 16 karakter
        if len(current_line) + len(word) + 1 > max_char_per_baris:
            if current_line:  # Simpan baris saat ini jika tidak kosong
                lines.append(current_line)
            current_line = word
        else:
            if current_line:
                current_line += " " + word
            else:
                current_line = word
    
    # Tambahkan baris terakhir
    if current_line:
        lines.append(current_line)
    
    # Batasi maksimal 4 baris
    if len(lines) > 4:
        lines = lines[:4]
        # Tambahkan "..." di baris terakhir jika ada teks yang terpotong
        if len(lines[3]) < max_char_per_baris - 3:
            lines[3] += "..."
        else:
            lines[3] = lines[3][:max_char_per_baris-3] + "..."
    
    # Tampilkan dengan font vertical stretch center
    tampilkan_font_vertical_stretch_center(lines)

# --- FUNGSI TAMPILAN OLED YANG SUDAH DIUPGRADE ---
def oled_show_vertical_stretch(line1, line2="", line3="", line4=""):
    """
    Menampilkan 4 baris dengan font vertical stretch dan center alignment
    """
    lines = [line1, line2, line3, line4]
    # Hapus string kosong dari akhir
    while lines and lines[-1] == "":
        lines.pop()
    
    tampilkan_font_vertical_stretch_center(lines)

def oled_center_multiline_vertical_stretch(lines):
    """
    Menampilkan multiple lines dengan font vertical stretch dan center alignment
    """
    # Filter lines yang tidak kosong atau berisi spasi untuk spacing
    filtered_lines = []
    for line in lines:
        if line.strip():  # Jika line tidak kosong
            filtered_lines.append(line.strip())
        elif len(filtered_lines) > 0 and len(filtered_lines) < 4:
            # Tambah line kosong untuk spacing hanya jika belum 4 baris
            filtered_lines.append("")
    
    # Batasi maksimal 4 baris
    if len(filtered_lines) > 4:
        filtered_lines = filtered_lines[:4]
    
    tampilkan_font_vertical_stretch_center(filtered_lines)

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
    """Sinkronisasi cache dengan power-safe method"""
    global rfid_cache, organization_name
    print("Mulai sinkronisasi cache RFID (Power-Safe)...")
    
    # Pastikan WiFi terkoneksi
    if not ensure_wifi_connection():
        oled_center_multiline_vertical_stretch([
            "Sinkronisasi",
            "Gagal!",
            "WiFi Error",
            ""
        ])
        danger()
        return False
    
    oled_center_multiline_vertical_stretch(["Sinkronisasi", "Ke Server..."])
    
    # Ambil nama organisasi dengan retry
    for attempt in range(2):  # 2 attempts untuk org name
        try:
            org_url = f"{SUPABASE_URL}/rest/v1/organizations?id=eq.{organization_id}&select=name"
            headers = {
                'apikey': SUPABASE_KEY, 
                'Authorization': f'Bearer {SUPABASE_KEY}',
                'Connection': 'close'
            }
            org_response = urequests.get(org_url, headers=headers, timeout=10)
            
            if org_response.status_code == 200:
                org_data = org_response.json()
                if org_data:
                    organization_name = org_data[0]['name']
                    print(f"Organisasi ditemukan: {organization_name}")
                    org_response.close()
                    break
            org_response.close()
            
        except Exception as e:
            print(f"Error mengambil data organisasi (attempt {attempt + 1}): {e}")
            if attempt == 1:  # Last attempt
                organization_name = "Unknown Org"
    
    # Ambil data RFID dengan retry
    for attempt in range(2):  # 2 attempts untuk RFID data
        try:
            query = "card_number,organization_member_id,organization_members(user_profiles(first_name,last_name),departments!organization_members_department_id_fkey(name))"
            url = f"{SUPABASE_URL}/rest/v1/rfid_cards?select={query}"
            headers = {
                'apikey': SUPABASE_KEY, 
                'Authorization': f'Bearer {SUPABASE_KEY}',
                'Connection': 'close'
            }
            
            response = urequests.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                rfid_cache = {}
                
                for item in data:
                    try:
                        profile = item.get('organization_members', {}).get('user_profiles', {})
                        name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
                        if not name: name = "Nama Kosong"
                    except (TypeError, KeyError):
                        name = "ErrorNama"
                    
                    try:
                        department_data = item.get('organization_members', {}).get('departments')
                        if department_data:
                            department_name = department_data.get('name', 'No Dept')
                        else:
                            department_name = "No Dept"
                    except (TypeError, KeyError):
                        department_name = "Unknown Dept"
                    
                    rfid_cache[item['card_number']] = {
                        'member_id': item['organization_member_id'],
                        'name': name,
                        'department': department_name
                    }
                
                response.close()
                print(f"Sinkronisasi berhasil! {len(rfid_cache)} kartu dimuat.")
                oled_center_multiline_vertical_stretch(["Sinkronisasi", "Berhasil"])
                muat()
                return True
                
            else:
                response.close()
                print(f"Sync attempt {attempt + 1} failed. Status: {response.status_code}")
                
        except Exception as e:
            print(f"Error saat sinkronisasi cache (attempt {attempt + 1}): {e}")
        
        if attempt < 1:  # If not the last attempt
            time.sleep(2)
    
    # Jika semua attempt gagal
    oled_center_multiline_vertical_stretch(["Sinkronisasi", "Gagal!"])
    danger()
    return False

    # --- PERBAIKAN SELESAI ---

def upload_attendance_batch():
    """Upload dengan retry mechanism dan power-safe operations"""
    global attendance_queue
    
    if not attendance_queue:
        return True
    
    # Batasi ukuran batch untuk mengurangi beban
    batch_to_send = attendance_queue[:BATCH_SIZE_LIMIT] if len(attendance_queue) > BATCH_SIZE_LIMIT else attendance_queue.copy()
    
    print(f"\n--- Mode Upload Power-Safe ---")
    print(f"Mengirim {len(batch_to_send)} data absensi (dari {len(attendance_queue)} total)...")
    
    # Display progress
    oled_center_multiline_vertical_stretch([
        "Mengirim Data",
        f"{len(batch_to_send)} item",
        "Ke Server...",
        ""
    ])
    
    for attempt in range(MAX_RETRY_UPLOAD):
        try:
            # Step 1: Pastikan WiFi terkoneksi dengan baik
            if not ensure_wifi_connection():
                print(f"Upload attempt {attempt + 1}: WiFi connection failed")
                if attempt < MAX_RETRY_UPLOAD - 1:
                    oled_center_multiline_vertical_stretch([
                        "WiFi Bermasalah",
                        f"Percobaan {attempt + 1}",
                        "Mengulang...",
                        ""
                    ])
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                else:
                    oled_center_multiline_vertical_stretch([
                        "Upload Gagal",
                        "WiFi Error",
                        "Coba Lagi Nanti",
                        ""
                    ])
                    danger()
                    return False
            
            # Step 2: Siapkan request dengan timeout
            url = f"{SUPABASE_URL}/rest/v1/rpc/handle_attendance_batch"
            headers = {
                'apikey': SUPABASE_KEY, 
                'Authorization': f'Bearer {SUPABASE_KEY}', 
                'Content-Type': 'application/json',
                'Connection': 'close'  # Tutup koneksi setelah request
            }
            payload = {'taps': batch_to_send}
            
            # Step 3: Kirim dengan timeout dan error handling
            print(f"Upload attempt {attempt + 1}...")
            
            # Set timeout untuk urequests (jika didukung)
            response = urequests.post(
                url, 
                headers=headers, 
                data=json.dumps(payload),
                timeout=HTTP_TIMEOUT  # Timeout 15 detik
            )
            
            # Step 4: Periksa respons
            if response.status_code == 200:
                response_text = response.text
                response.close()
                
                if 'BATCH_PROCESSED' in response_text:
                    print("Upload batch berhasil!")
                    success()
                    
                    # Hapus data yang berhasil dikirim
                    if len(attendance_queue) <= BATCH_SIZE_LIMIT:
                        attendance_queue = []
                    else:
                        attendance_queue = attendance_queue[BATCH_SIZE_LIMIT:]
                    
                    oled_center_multiline_vertical_stretch([
                        "Upload Sukses",
                        f"{len(batch_to_send)} data",
                        "terkirim",
                        ""
                    ])
                    time.sleep(1)
                    return True
                else:
                    print(f"Server response unexpected: {response_text}")
                    response.close()
                    
            else:
                print(f"HTTP Error {response.status_code}: {response.text}")
                response.close()
                
        except OSError as e:
            print(f"Upload attempt {attempt + 1} - Network error: {e}")
        except Exception as e:
            print(f"Upload attempt {attempt + 1} - Unexpected error: {e}")
        
        # Jika belum berhasil dan masih ada attempt
        if attempt < MAX_RETRY_UPLOAD - 1:
            oled_center_multiline_vertical_stretch([
                "Upload Gagal",
                f"Percobaan {attempt + 1}",
                "Mengulang...",
                ""
            ])
            warning()
            time.sleep(RETRY_DELAY_SECONDS)
        else:
            # Attempt terakhir gagal
            oled_center_multiline_vertical_stretch([
                "Upload Gagal",
                "Coba Lagi Nanti",
                f"{len(attendance_queue)} data",
                "tersimpan"
            ])
            danger()
            return False
    
    return False

# --- PROGRAM UTAMA ---
# 1. Tampilkan Layar Booting dengan Font Vertical Stretch
lines_to_show = [
    "Mesin Presensi",
    "Oleh",
    "PT Universal",
    "Big Data"
]
oled_center_multiline_vertical_stretch(lines_to_show)
time.sleep(2.0)

lines_to_show = [
    f"Ver: {_VERSION}",
    "---------------",
    "SN: 028192812"
]
oled_center_multiline_vertical_stretch(lines_to_show)
time.sleep(2.0)

oled_wrap_center_vertical_stretch(organization_name)
time.sleep(2.0)

# 2. Inisialisasi Koneksi
oled_wrap_center_vertical_stretch("Inisialisasi Pengaturan....")
if connect_wifi():
    sync_time()
    time.sleep(0.5)
    sync_rfid_cache()
    time.sleep(0.5)
else:
    oled_show_vertical_stretch("Error", "Gagal WiFi"); danger()

# Default message untuk idle state
default_message = [
    organization_name,
    "Scan Kartu Anda!"
]

# 3. Siap Beroperasi
print(f"\n===== Sistem Absensi Siap (v{_VERSION}) =====")
oled_center_multiline_vertical_stretch(default_message)
siapDigunakan()
last_tap_time = time.time()

# --- LOOP UTAMA ---
while True:
    current_millis = time.ticks_ms()

    # Blok 1: Reset Tampilan OLED setelah Timeout (Non-Blocking)
    if oled_is_displaying_message and time.ticks_diff(current_millis, oled_message_timer) > OLED_MESSAGE_DURATION_MS:
        oled_center_multiline_vertical_stretch(default_message)
        oled_is_displaying_message = False

    # Blok 2: Deteksi Idle dan Upload
    if time.time() - last_tap_time > IDLE_TIMEOUT_SECONDS:
        if attendance_queue:
            oled_wrap_center_vertical_stretch("Mengirim Data Ke Server...")
            upload_attendance_batch()
            oled_center_multiline_vertical_stretch(default_message)
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
                department = user_data['department']
                
                # Tampilkan nama dengan font vertical stretch
                oled_center_multiline_vertical_stretch([
                    organization_name,
                    "Berhasil",
                    f"{name}",
                    department
                ])
                
                # Proses data absensi
                member_id = user_data['member_id']; current_time_tuple = time.localtime()
                timestamp_str = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(*current_time_tuple[0:6])
                attendance_queue.append({'member_id_input': member_id, 'event_time_input': timestamp_str})
                print(f"Antrean: {len(attendance_queue)} | Kartu OK: {name} - {department} ({uid_str})")
            else:
                # Tampilkan pesan error dengan font vertical stretch
                oled_center_multiline_vertical_stretch([
                    organization_name,
                    "Tidak terdaftar",
                    f"ID {uid_str}",
                    ""
                ])
                print(f"Kartu Ditolak: {uid_str}"); warning()

            last_tap_time = time.time()
            oled_message_timer = current_millis
            oled_is_displaying_message = True
            
    time.sleep_ms(50)