# Home

## Propósito

Este directorio constituye el espacio de persistencia del proyecto.

Aquí deben almacenarse todos los datos que deban sobrevivir al ciclo de vida de la aplicación y a la recreación del entorno de ejecución.

## Responsabilidad

Este directorio no contiene código fuente.

Su contenido depende de la implementación del proyecto y del Stack Contract correspondiente.

Puede incluir, entre otros:

- Bases de datos.
- Archivos de configuración persistentes.
- Archivos generados por la aplicación.
- Almacenamiento de usuarios.
- Cachés persistentes.
- Logs persistentes.

## Contrato

Todo proyecto MEKA debe disponer de un directorio `home/`.

La organización interna es libre y depende de las necesidades del proyecto.

La infraestructura del proyecto podrá montar este directorio como volumen persistente durante la ejecución.