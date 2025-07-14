import json
import time
import os

# Mapa de flags de ADC con nombres legibles
FLAG_NAMES = {
    0x00: "DafUnipolar",         # misma clave que DafUnsigned, se combinan
    0x02: "DafBipolar",
    0x04: "DafSigned",
    0x08: "DafDifferential",
    0x0000: "DafSingleEndedLow",
    0x1000: "DafSingleEndedHigh",
    0x10: "DafSSHHold",
    0x00: "DafSSHSample",
    0x00: "DafAnalog",
    0x01: "DafHighSpeedDigital",
    0x001: "DafDigital8",
    0x101: "DafDigital16",
    0x2001: "DafP2Local8",
    0x4001: "DafP2Exp8",
    0x0001: "DafP3Local16"
}

def decode_flags(flag_value):
    """Devuelve una lista con los nombres de los flags que están activados en flag_value."""
    nombres = []
    for bitmask, name in FLAG_NAMES.items():
        if bitmask != 0 and (flag_value & bitmask) == bitmask:
            nombres.append(name)
    if flag_value == 0:
        nombres.append("DafAnalog+Unipolar+SingleEnded")
    return nombres

def guardar_metadata(file_name, frecuencia, canales, ganancias, flags):
    """Guarda metadatos de adquisición en un archivo JSON."""
    metadata = {
        "frecuencia_Hz": frecuencia,
        "canales": canales,
        "ganancias": ganancias,
        "flags": [decode_flags(f) for f in flags],
        "fecha": time.ctime()
    }
    metadata_filename = file_name.replace(".bin", "_metadata.json")
    with open(metadata_filename, "w") as f:
        json.dump(metadata, f, indent=4)
    print(f"[INFO] Metadatos guardados en {metadata_filename}")

def actualizar_metadata_final(file_name, total_scans):
    meta_file = file_name.replace(".bin", "_metadata.json")
    if os.path.exists(meta_file):
        with open(meta_file, 'r+') as f:
            data = json.load(f)
            data["scans_totales"] = total_scans
            f.seek(0)
            json.dump(data, f, indent=4)
            f.truncate()
