# Impor library yang dibutuhkan
from machine import Pin, I2C
import ssd1306 # Impor file library yang sudah Anda simpan
import time

# Konfigurasi Pin I2C sesuai dengan koneksi Anda
# SCL -> GPIO 22
# SDA -> GPIO 21
i2c = I2C(0, scl=Pin(22), sda=Pin(21))

# Konfigurasi dimensi layar OLED (biasanya 128x64 untuk modul 0.96 inch)
SCREEN_WIDTH = 128
SCREEN_HEIGHT = 64

# Inisialisasi objek OLED
# Gunakan kelas SSD1306_I2C dari library
oled = ssd1306.SSD1306_I2C(SCREEN_WIDTH, SCREEN_HEIGHT, i2c)

# -- Program Utama Dimulai --

# 1. Bersihkan layar (mengisi dengan warna hitam/piksel mati)
oled.fill(0)

# 2. Tulis teks ke buffer
# format: oled.text("Teks Anda", x, y)
# x = posisi horizontal, y = posisi vertikal
oled.text("Hello, World!", 0, 10)
oled.text("ESP32 + OLED", 0, 30)

# 3. Tampilkan isi buffer ke layar
oled.show()

print("Pesan 'Hello, World!' telah ditampilkan di layar OLED.")