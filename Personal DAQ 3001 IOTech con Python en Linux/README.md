# Personal DAQ 3001 en Linux con pyIOTech

Este repositorio permite usar la **Personal DAQ 3001** (IOtech / Measurement Computing) en **Linux**,
sin Windows y sin `DaqX64.dll`, con la **misma interfaz que pyIOTech**. Los programas escritos para
Windows (`from PyIOTech import daq, daqh`) funcionan sin cambios.

El paquete `PyIOTech/` de este repositorio reemplaza a la biblioteca original: en lugar de llamar a la
DLL, habla directamente con la placa por USB (con `libusb`). El protocolo se reconstruyó a partir de
capturas USB del driver de Windows; está documentado en [`docs/protocolo.md`](docs/protocolo.md).

---

## Instalación

1. **Dependencias del sistema y de Python**

   ```bash
   sudo apt install libusb-1.0-0 python3-venv
   git clone https://github.com/laboratorio-turbulencia-geofisica/Comunicacion-con-instrumentos.git
   cd "Comunicacion-con-instrumentos/Personal DAQ 3001 IOTech con Python en Linux"
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Permisos USB** (una sola vez), para usar la placa sin `sudo`:

   ```bash
   sudo cp udev/99-pdaq3000.rules /etc/udev/rules.d/
   sudo udevadm control --reload-rules && sudo udevadm trigger
   ```

3. **Firmware de la placa**
   La placa necesita dos archivos de firmware que son propiedad de IOtech/Measurement Computing y por
   eso **no se incluyen** en este repositorio. Se extraen de los drivers de Windows que instala
   **DAQView** (ver la [guía de instalación en Windows](../Personal%20DAQ%203001%20IOTech%20con%20Python)):
   copiar desde una PC con DAQView instalado los archivos `pdaq3kld.sys` y `pdaq3k.sys`
   (habitualmente en `C:\Windows\System32\drivers\` o en `C:\Program Files (x86)\DaqX\Drivers\USB_x64\`)
   y correr:

   ```bash
   python tools/extraer_firmware.py ruta/a/pdaq3kld.sys ruta/a/pdaq3k.sys
   ```

   Esto genera `PyIOTech/pdaq3k_fx2.ihx` y `PyIOTech/pdaq3001_fpga.bin` y verifica que coincidan con
   la versión probada.

4. **Conexión**
   > **IMPORTANTE:** Siempre conectar primero la placa a la fuente de alimentación externa
   > (transformador AC/DC de 12 V) y luego a la computadora.

   La primera vez que se abre la placa después de enchufarla, el driver le carga el firmware y la FPGA
   (unos 5 s; se encienden los LEDs). Las aperturas siguientes tardan ~0,1 s.

---

## VERIFICAR CORRECTA INSTALACIÓN:
Listar los dispositivos conectados con `ennumerate_devices.py`:

```python
from PyIOTech import daq

count = daq.GetDeviceCount()
print("Dispositivos encontrados:", count)

for i, name in enumerate(daq.GetDeviceList()):
    print(f"[{i}] Nombre: {name}")
```

Si todo funcionó correctamente deberían tener algo del estilo:
```
Dispositivos encontrados: 1
[0] Nombre: b'PersonalDaq3001'
```
> En Linux el nombre del dispositivo se ignora: `daq.daqDevice(b'PersonalDaq3001{374679}')` abre la
> placa conectada, sea cual sea el número de serie.

## LEER UN CANAL:
Lo más básico es leer el voltaje de un único canal, con `read_single_channel_value.py`. Conectar la
salida del generador de funciones al canal 0 de los analog inputs de la placa.
> **IMPORTANTE**: todas las mediciones, single-ended y diferenciales, se realizan respecto al common,
> así que poner ahí la tierra del generador.

```python
from PyIOTech import daq, daqh

device_name = b'PersonalDaq3001{374679}'
channel = 0
gain = daqh.DgainX1
flags = daqh.DafAnalog | daqh.DafUnsigned | daqh.DafBipolar | daqh.DafDifferential
max_voltage = 10.0
bit_depth = 16

try:
    dev = daq.daqDevice(device_name)
    data = dev.AdcRd(channel, gain, flags)
    # Convertir de entero sin signo a voltaje bipolar.
    data = data*max_voltage*2/(2**bit_depth) - max_voltage
    print(data)
finally:
    dev.Close()
```

## ARMAR SCANEO:
Para leer de forma continua uno o varios canales hay que armar un scaneo como en `scan.py`.

## GUARDAR DIRECTO EN DISCO:
Para medir durante tiempos largos hay que guardar los datos binarios directamente en disco, para no
sobrecargar la memoria. Ver `direct_to_disk.py`.

## OTROS EJEMPLOS Y COSAS ÚTILES:
En `osciloscope.py` hay un programa que lee los canales especificados y grafica el resultado.
En `measure_interface.py` hay una GUI para adquirir de forma más cómoda; guarda además la metadata de
la configuración del escaneo. Ambos dependen de `Formatter.py` para convertir los valores binarios a
voltaje.

## USAR PROGRAMAS QUE YA TENÍAN PARA WINDOWS:
Reemplazar la carpeta `PyIOTech/` que esté junto al programa por la de este repositorio (o un enlace
simbólico a ella). No hace falta cambiar nada más.

---

## DIFERENCIAS CON LA VERSIÓN DE WINDOWS

- **Calibración de fábrica aplicada por defecto.** El driver lee la tabla de calibración de la EEPROM
  y corrige ganancia y offset de cada rango, como `DaqX64.dll`. Para obtener las cuentas crudas:
  `daq.daqDevice(nombre, calibrate=False)`.
- **Límite de 1 MS/s en total** (frecuencia × cantidad de canales). Es un límite del hardware: si se
  pide más, la placa adquiere más lento de lo que informa `AdcGetFreq()`. El driver imprime un aviso.
  Por ejemplo, con 2 canales usar como máximo 500 kHz por canal.
- **`AdcSetDiskFile` vale para una sola adquisición**: hay que volver a llamarlo antes de cada
  adquisición (así no se pisa un archivo por accidente).
- **Funciones implementadas:** `AdcSetScan`, `AdcSetFreq`/`AdcGetFreq`, `AdcSetRate`, `AdcSetAcq`
  (`DaamNShot`, `DaamInfinitePost`), `AdcSetTrig` (`DatsImmediate`, `DatsSoftware`), `AdcSoftTrig`,
  `AdcTransferSetBuffer` (incluido `DatmCycleOn`), `AdcSetDiskFile`, `AdcArm`/`AdcDisarm`,
  `AdcTransferStart`/`Stop`, `AdcTransferGetStat`, `WaitForEvent` (`DteAdcData`, `DteAdcDone`),
  `AdcRd`, `AdcRdScan`, `SetTimeout`, `GetDeviceList`, `GetDeviceCount`.
- **No implementado todavía:** salida del DAC en forma de onda, disparo por hardware, E/S digital y
  contadores. `DacWt` está pero sin verificar.

## VALIDACIÓN
Probado con un generador Tektronix AFG3021B:

| Prueba | Resultado |
|---|---|
| Adquisición continua | 1 MS/s sostenido, sin pérdida de muestras (10 M muestras a disco) |
| Linealidad (x1) | residuo < 0,8 mV en ±8 V |
| Ganancias x1 … x100 | dispersión entre rangos 0,27 % con la calibración de fábrica |
| Respuesta en frecuencia | plana desde 0,1 Hz (sin pasa altos); −2,3 % a 200 kHz |
| Retardo entre canales | 1,0093 µs (multiplexado); a 50 kHz equivale a 18° y el resampleo con FDF lo corrige |
| Impedancia de entrada | 46 MΩ ∥ 4,6 pF |

> Los canales se convierten uno después del otro, separados ~1 µs. Para medir fases entre canales
> hay que corregir ese retardo (por ejemplo, interpolando la referencia con un filtro de retardo
> fraccional).

## CÓMO FUNCIONA
- `PyIOTech/daq.py`: interfaz compatible con pyIOTech.
- `PyIOTech/_pdaq3k.py`: comunicación USB (carga de firmware, registros de la FPGA, streaming).
- `PyIOTech/daqh.py`: constantes de `Daqx.h`, de pyIOTech.
- `docs/protocolo.md`: descripción del protocolo.
- `tools/pcap_to_ops.py` y `tools/replay.py`: herramientas usadas para la ingeniería inversa
  (convierten capturas USBPcap de Windows en secuencias reproducibles en Linux).

## CRÉDITOS Y LICENCIA
- Basado en [pyIOTech](https://github.com/fake-name/PyIOTech) (GPLv2), del que proviene `daqh.py`
  y la interfaz de `daq.py`.
- El firmware del FX2 y el bitstream de la FPGA son propiedad de IOtech / Measurement Computing y no
  se distribuyen; se extraen de los drivers que cada usuario tenga instalados.
- Este repositorio se distribuye bajo la licencia **GPLv2** (ver `LICENSE`).
