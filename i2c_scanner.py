from machine import Pin, I2C

# Gunakan pin I2C standar ESP32
i2c = I2C(0, scl=Pin(22), sda=Pin(21))

print('Mencari perangkat I2C...')
devices = i2c.scan()

if len(devices) == 0:
    print("Tidak ada perangkat I2C yang ditemukan!")
else:
    print('Perangkat I2C ditemukan:', len(devices))
    for device in devices:
        print("Alamat Desimal:", device, "| Alamat Heksadesimal:", hex(device))