# Guía de instalación y uso de la Personal DAQ 3001 con pyIOTech

Este repositorio contiene ejemplos básicos para la instalación y utilización de la Personal DAQ 3001 de IOTech mediante la biblioteca **pyIOTech**.

---

## Instalación

1. **Instalar pyIOTech**  
   El paquete `pyIOTech` utilizado aquí está actualizado a Python 3.10 respecto a la versión original disponible en:  
   [https://github.com/fake-name/PyIOTech](https://github.com/fake-name/PyIOTech)

2. **Instalar drivers de la placa**  
   Los drivers se descargan automáticamente al instalar **DAQView**, el software oficial de control de la placa por Digilent:  
   [https://digilent.com/reference/software/daqview/start?srsltid=AfmBOooFsE4jjApApYb2sRodq8S748rPI4rqD25JxMetY838RgOaZ7j0](https://digilent.com/reference/software/daqview/start?srsltid=AfmBOooFsE4jjApApYb2sRodq8S748rPI4rqD25JxMetY838RgOaZ7j0)  

   > **Nota:** Para descargar el instalador es necesario crear una cuenta en la página.

3. **Configuración inicial**  
   - Conectar la placa por USB y abrir la aplicación **DAQView** por primera vez para que se instalen los drivers automáticamente.  
   - **IMPORTANTE:** Siempre conectar primero la placa a la fuente de alimentación externa (transformador AC/DC de 12 V) y luego a la computadora, para evitar que la placa solicite demasiada energía al PC al iniciar la comunicación.

4. **Ubicación de `DaqX64.dll`**  
   Verificar la ubicación del archivo `DaqX64.dll` que generalmente se encuentra en:  
   `C:\Program Files (x86)\DaqX\Drivers\USB_x64`  

   Si está en otra ruta, modificar al inicio del archivo `daq.py` la ubicación correcta.  

   > **IMPORTANTE:** Usar la versión del `.dll` que coincida con la arquitectura (32 o 64 bits) de la versión de Python instalada en el sistema.

---

Una vez completados estos pasos, la placa debería estar lista para usarse con los ejemplos incluidos en este repositorio.


## VERIFICAR CORRECTA INSTALACIÓN:
Para verificar que todo está funcionando correctamente podemos empezar por listar los dispositivos conectados, corriendo el archivo `enummerate_devices.py`. 

```
from PyIOTech import daq

count = daq.GetDeviceCount()  
print("Dispositivos encontrados:", count)

for i, name in enumerate(daq.GetDeviceList()):
    print(f"[i] Nombre: {name}")
``` 

Si todo funcionó correctamente deberían tener algo del estilo: 
```
Dispositivos encontrados: 1
[0] Nombre: b'PersonalDaq3001{374679}'
```

## LEER UN CANAL:
Lo más básico que podemos hacer es leer el voltaje de un único canal, corriendo `read_single_channel_value.py`. Podemos conectar la salida del generador de funciones al canal 0 de los analogs input de la placa. 
> **IMPORTANTE**: todas las mediciones, single-ended como differential se realizan respecto al common, así que poner ahí la Tierra del generador. 

```
from PyIOTech import daq, daqh

device_name = b'PersonalDaq3001{374679}' # <-- Your device here.
channel = 0
gain = daqh.DgainX1
flags = daqh.DafAnalog | daqh.DafUnsigned | daqh.DafBipolar | daqh.DafDifferential
max_voltage = 10.0
bit_depth = 16

try:
    dev = daq.daqDevice(device_name)
    data = dev.AdcRd(channel, gain, flags)
    # Convert sample from unsigned integer value to bipolar voltage.
    data = data*max_voltage*2/(2**bit_depth) - max_voltage
    print(data)
finally:
    dev.Close()
```

Este código lee un único valor en modo diferencial del canal 0 y lo convierte a voltaje. 

## ARMAR SCANEO:
Para leer de forma continua uno o varios canales hay que armar un scaneo como en el archivo `scan.py`.

## GUARDAR DIRECTO EN DISCO:
Para poder medir durante un tiempo relativamente largo, mayor a un par de segundos, habrá que guardar los datos binarios directamente en disco, para no sobrecargar la memoria. 
Este procedimiento se muestra en `direct_to_disk.py`.

## OTROS EJEMPLOS Y COSAS ÚTILES:
En `osciloscope.py` hay un programa que lee el voltaje de los canales especificados y grafica el resultado. 
En `measure_interface.py` hay una GUI para adquirir de forma más cómoda de los canales especificados. Guarda además la metadata de la configuración de ese escaneo específico. 
Ambos archivos dependen de `Formatter.py` para convertir los valores binarios a voltaje.  

