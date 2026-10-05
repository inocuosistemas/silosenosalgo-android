# SiLoSeNoSalgo para Android

La app para seguir carreras y salidas en directo, con baliza, previsión del tiempo y radar de lluvia.

**Descargar la última versión:** [SiLoSeNoSalgo.apk](https://github.com/inocuosistemas/silosenosalgo-android/releases/latest/download/SiLoSeNoSalgo.apk)

Al abrir el enlace desde el móvil, Android pide permiso para instalar apps de fuera de la tienda: hay que darlo una vez. La app avisa sola cuando sale una versión nueva.

También está en Google Play (pruebas) para quien esté apuntado.

Aquí solo están las versiones para instalar; el código no está en este repositorio.

## Horario previsto de Rodalies

`datos/rodalies.json` se genera cada lunes (`.github/workflows/horarios-rodalies.yml`)
con `scripts/genera-rodalies.py` a partir del calendario oficial de Renfe
(datos abiertos, data.renfe.com). La app lo usa cuando el servicio de horarios
de Rodalies no contesta.
