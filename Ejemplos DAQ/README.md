Guía para la instalación y utilización de la Personal DAQ 3001 de IOTech mediante pyIOTech. A continuación se encuentran varios ejemplos básicos.

INSTALACIÓN: 
Se deben instalar por un lado el paquete pyIOTech, la versión de este repo está actualizada a Python 3.10 respecto a la del reppo original (https://github.com/fake-name/PyIOTech). 
Por otro lado hay que instalar los drivers de la placa, que se bajan automáticamente al descargar DAQView, el programa original de control de la placa por Digilent (https://digilent.com/reference/software/daqview/start?srsltid=AfmBOooFsE4jjApApYb2sRodq8S748rPI4rqD25JxMetY838RgOaZ7j0). Pide crear una cuenta para poder descargar el instalador. 
Hay que abrir la aplicación por primera vez para que instale los drivers de la placa (con la misma conectada por USB). IMPORTANTE: Conectar siempre primero la placa a la potencia externa mediante el transformador AC/DC de 12 V, y después a la computadora, para que pida el mínimo de energía a la misma al iniciar la comunicación. 

Una vez instalada la placa y DAQView revisar la ubicación de "DaqX64.dll", probablemente esté en "C:\Program Files (x86)\DaqX\Drivers\USB_x64" pero sino tendrán que cambiar al inicio de daq.py la ubicación del mismo. IMPORTANTE: Usar el ".dll" qie sea de los mismos bits que la versión de Python que se esté usando en el sistema. 
Ya debería estar lista para usarse la placa. 

VERIFICAR CORRECTA INSTALACIÓN:
Para verificar que todo está funcionando correctamente podemos empezar por listar los dispositivos conectados, corriendo el archivo "enummerate_devices.py". 

´´´
from PyIOTech import daq

count = daq.GetDeviceCount()  
print("Dispositivos encontrados:", count)

for i, name in enumerate(daq.GetDeviceList()):
    print(f"[i] Nombre: {name}")
´´´ 

Si todo funcionó correctamente deberían tener algo del estilo: 
´´´
Dispositivos encontrados: 1
[0] Nombre: b'PersonalDaq3001{374679}'
´´´

LEER UN CANAL:
Lo más básico que podemos hacer es leer el voltaje de un único canal, corriendo "read_single_channel_value.py". Podemos conectar la salida del generador de funciones al canal 0 de los analogs input de la placa. IMPORTANTE: todas las mediciones, single-ended como differential se realizan respecto al common, así que poner ahí la Tierra del generador. 

´´´
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
´´´

Este código lee un único valor en modo diferencial del canal 0 y lo convierte a voltaje. 

ARMAR SCANEO:
Para leer de forma continua uno o varios canales hay que armar un scaneo como en el archivo "scan.py".

GUARDAR DIRECTO EN DISCO:
Para poder medir durante un tiempo relativamente largo, mayor a un par de segundos, habrá que guardar los datos binarios directamente en disco, para no sobrecargar la memoria. 
Este procedimiento se muestra en "direct_to_disk.py"

OTROS EJEMPLOS Y COSAS ÚTILES:
En "osciloscope.py" hay un programa que lee el voltaje de los canales especificados y grafica el resultado. 
En "measure_interface.py" hay una GUI para adquirir de forma más cómoda de los canales especificados. Guarda además la metadata de la configuración de ese escaneo específico. 
Ambos archivos dependen de "Formatter.py" para convertir los valores binarios a voltaje.  

