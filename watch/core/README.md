# Gemeinsamer Schlafphasen-Kern

Dieses JVM-Modul enthält die gemeinsamen Schlafphasen-Wire-Werte und die
Vergleichsrechnung, die Watch- und Smartphone-App verwenden.

## Build

- Bytecode-Ziel: JVM 17.
- Es wird keine JDK-17-Toolchain heruntergeladen oder vorausgesetzt.
- Gradle verwendet das im Android-CI-Image vorhandene JDK; der Kotlin-Compiler
  schreibt kompatiblen JVM-17-Bytecode.

Die Sensoradapter und der lokale IBI-Speicher bleiben ausschließlich im
Watch-Modul. Health Connect bleibt ausschließlich in der Smartphone-App.
