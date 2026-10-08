from PyIOTech import daq

count = daq.GetDeviceCount()  
print("Dispositivos encontrados:", count)

for i, name in enumerate(daq.GetDeviceList()):
    print(f"[{i}] Nombre: {name}")
