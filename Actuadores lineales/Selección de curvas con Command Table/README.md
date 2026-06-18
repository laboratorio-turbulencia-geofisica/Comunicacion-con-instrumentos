Logré configurar el =Command Table= para alternar entre 2 curvas. Para poder hacer esto:
1) Cargar las curvas deseadas en la memoria del drive del motor. Para esto hay que subirlas a LinMot Talk en la sección de =Curves= de la izquierda como se hace usualmente, con el cuidado de ir cambiando el =Curve ID= en =Curve Properties=.

2) En =Run Mode Selection= que se encuentra en el árbol de la izquierda hay que seleccionar =Command Table Mode=, por defecto está puesto en =Continuous Curve=.

#+ATTR_ORG: :width 500
[[file:../../../Assets/2026/06/Day_17/run_mode_settings.jpg]]

3) Hay que cargar en la sección de =Command Table= de la izquierda los comandos para seleccionar las curvas:

#+ATTR_ORG: :width 500
[[file:../../../Assets/2026/06/Day_17/Command_Table.jpg]]

Por ejemplo para alternar entre la curva con =ID=1= y la curva con =ID=2= e ir ciclando entre ellas se puede utilizar:

|----------+------------+-------------------------+-------------------------------------------------+----------+----------------------------------------+-----------------------|
| Entry ID | Entry Name | Motion Command Category | Motion Command Type                             | Curve ID | Auto Execute new command on next cycle | ID of Sequenced Entry |
|----------+------------+-------------------------+-------------------------------------------------+----------+----------------------------------------+-----------------------|
|        1 | Curve1     | Time Curve              | Time Curve With Default Parameters From Act Pos | 1        | True                                   |                     2 |
|        2 | wait       | Conditions              | Wait until Motion Finished                      | -        | True                                   |                     3 |
|        3 | Curve2     | Time Curve              | Time Curve With Default Parameters From Act Pos | 2        | True                                   |                     4 |
|        4 | wait       | Conditions              | Wait until Motion Finished                      | -        | True                                   |                     1 |
|----------+------------+-------------------------+-------------------------------------------------+----------+----------------------------------------+-----------------------|
Esto elige la curva, la ejecuta, espera que termine la ejecución y pasa a correr la siguiente. El /auto execute/ funciona un poco al estilo de las animaciones de PowerPoint, donde se configura para que la siguiente se corra al finalizar la anterior, y se dirige la última a la primera para que sea periódico.

4) En =Control Panel= como se hace usualmente se prende el firmware del motor:
   a) Se usa =Switch On= (la primera casilla marcada y la segunda se desmarca y se marca).
   b) Se hace el =homing=. Se marca la primera y segunda casilla, esto hace el =homing=.
   c) Se desmarca la segunda casilla del =homing= para habilitar el envío de comandos mediante la =Command Table=.

5) En el panel de abajo a la izquierda se configura la instrucción a enviar:

#+ATTR_ORG: :width 500
[[file:../../../Assets/2026/06/Day_17/send_command_table.jpg]]

Para esto se elige como comando =Start Command Table Command (200xh)= y en =Ccommand Table Entry ID= se elige la =Scaled Value = 1= para que empiece desde el principio. Hay que tildar el =Enable Manual Override= y =Auto Increment Count Nibble=.

6) Presionar el botón de =Send Command= y se va a empezar a ejecutar. En mi caso probé con dos senos de 100 mm de amplitud, uno rápido de 2 s de período y otro lento de 10 s de período para verificar el correcto funcionamiento.

Para más información está: [[https://www.youtube.com/watch?v=TgWFxDsaqco][Command Table Tutorial]].

Para exportar la Command Table desde =File: Export: Filename.lmc: Seleccionar Command Table=. El archivo de salida es un =.lmc=.  La idea ahora sería analizar ese archivo para poder escribir un código de Python que programáticamente arme otro =.lmc= que alternaría entre 10 Curves IDs aleatoriamente. La =Command Table= tiene hasta 255 líneas, con lo cual, al cada curva necesitar una para cargarla y otra para esperar a que termine, podríamos tener una 122 curvas, que si cada una dura unos 10 s serían unos 20 minutos de medición.

Sobre el archivo de configuración del =Command Table=: Pareciera ser una sucesión de bloques de corchetes =[...]= al estilo de JSON donde se guarda cada una de las 255 líneas de la tabla. En este caso hay solo 4 líneas llenas y 251 líneas vacías.

Una línea con comando es: =[A #1 42753 'Curve1' 4 1 [A 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 ] 2 ]=
Donde:
- La =A= está siempre.
- El =#1= o =#0= hablan de si esa línea está siendo usada.
- El =42753= está siempre.
- ="Curve1"= es el nombre del comando.
- =4= es la orden o comando. Para nosotros las relevantes son:
  + 4: ejecutar curva.
  + 33: esperar a terminar el movimiento.
- El =1= está siempre.
- El primer número del array da el =Curve ID= a ejecutar, para =wait= es 0.
- El =2= da la siguiente entrada de la =command table= a ejecutar.

