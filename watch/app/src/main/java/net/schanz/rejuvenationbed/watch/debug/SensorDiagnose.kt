package net.schanz.rejuvenationbed.watch.debug

import android.Manifest
import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorManager
import android.os.Build
import androidx.health.services.client.HealthServices
import androidx.health.services.client.MeasureCallback
import androidx.health.services.client.data.Availability
import androidx.health.services.client.data.DataPointContainer
import androidx.health.services.client.data.DataType
import androidx.health.services.client.data.DeltaDataType
import net.schanz.rejuvenationbed.watch.health.WearHealthPermissions

/** Was die Uhr an Kanälen meldet (Health Services, passiv und live). */
data class KanalBericht(
    val passiv: List<String>,
    val aktivitaetsZustaende: List<String>,
    val live: List<String>,
    val fehler: String?
)

object SensorDiagnose {
    /** Fragt passive und Live-Fähigkeiten ab und protokolliert sie. */
    fun kanaele(context: Context, ergebnis: (KanalBericht) -> Unit) {
        val app = context.applicationContext
        val client = try {
            HealthServices.getClient(app)
        } catch (fehler: Exception) {
            val b = KanalBericht(emptyList(), emptyList(), emptyList(), fehler.javaClass.simpleName)
            DebugProtokoll.ereignis(app, "KANAL", "Health Services fehlt: ${b.fehler}")
            ergebnis(b)
            return
        }
        val passivZukunft = client.passiveMonitoringClient.getCapabilitiesAsync()
        passivZukunft.addListener({
            val passiv = runCatching { passivZukunft.get() }
            val liveZukunft = client.measureClient.getCapabilitiesAsync()
            liveZukunft.addListener({
                val live = runCatching { liveZukunft.get() }
                val bericht = KanalBericht(
                    passiv = passiv.getOrNull()?.supportedDataTypesPassiveMonitoring
                        ?.map { it.name }?.sorted() ?: emptyList(),
                    aktivitaetsZustaende = passiv.getOrNull()?.supportedUserActivityStates
                        ?.map { it.toString() }?.sorted() ?: emptyList(),
                    live = live.getOrNull()?.supportedDataTypesMeasure
                        ?.map { it.name }?.sorted() ?: emptyList(),
                    fehler = (passiv.exceptionOrNull() ?: live.exceptionOrNull())?.javaClass?.simpleName
                )
                DebugProtokoll.ereignis(
                    app, "KANAL",
                    "passiv=${bericht.passiv} zustaende=${bericht.aktivitaetsZustaende} " +
                        "live=${bericht.live}" + (bericht.fehler?.let { " fehler=$it" } ?: "")
                )
                ergebnis(bericht)
            }, app.mainExecutor)
        }, app.mainExecutor)
    }

    /** Alle Rechte, die die Sensor-Kette braucht, mit Stand. */
    fun rechte(context: Context): List<Pair<String, Boolean>> {
        val liste = buildList {
            add(WearHealthPermissions.heartRatePermission())
            WearHealthPermissions.backgroundHeartRatePermission()?.let { add(it) }
            add(Manifest.permission.ACTIVITY_RECOGNITION)
            if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
        }
        return liste.map { recht ->
            recht.substringAfterLast('.') to WearHealthPermissions.isGranted(context, recht)
        }
    }

    /** Hardware-Sensoren der Uhr (Typ, Name, Hersteller) ins Protokoll. */
    fun sensorenProtokollieren(context: Context): Int {
        val manager = context.getSystemService(SensorManager::class.java) ?: return 0
        val sensoren = manager.getSensorList(Sensor.TYPE_ALL)
        DebugProtokoll.ereignis(context, "SENSOR", "${sensoren.size} Sensoren")
        sensoren.forEach { s ->
            DebugProtokoll.ereignis(
                context, "SENSOR",
                "typ=${s.type} ${s.stringType.substringAfterLast('.')} | ${s.name} | ${s.vendor}" +
                    if (s.isWakeUpSensor) " | wake" else ""
            )
        }
        return sensoren.size
    }
}

/** Stand des Live-Pulstests. */
data class LiveStand(
    val laeuft: Boolean = false,
    val verfuegbarkeit: String = "—",
    val bpm: Double? = null,
    val werte: Int = 0,
    val seit: Long = 0L,
    val ersterWertNachMs: Long? = null,
    val fehler: String? = null
)

/**
 * Live-Test des Pulssensors über den MeasureClient (nur solange das
 * Debug-Blatt offen ist). Zeigt, ob der Sensor JETZT liefert, unabhängig
 * von den gebündelten passiven Lieferungen.
 */
class LivePuls(context: Context, private val melden: (LiveStand) -> Unit) {
    private val app = context.applicationContext
    private var stand = LiveStand()

    private val rueckruf = object : MeasureCallback {
        override fun onAvailabilityChanged(dataType: DeltaDataType<*, *>, availability: Availability) {
            val text = availability.toString()
            DebugProtokoll.ereignis(app, "LIVE", "Verfügbarkeit $text")
            setzen(stand.copy(verfuegbarkeit = text))
        }

        override fun onDataReceived(data: DataPointContainer) {
            val punkte = data.getData(DataType.HEART_RATE_BPM)
            if (punkte.isEmpty()) return
            val letzter = punkte.last().value
            val erster = stand.ersterWertNachMs ?: (System.currentTimeMillis() - stand.seit).also {
                DebugProtokoll.ereignis(app, "LIVE", "erster Wert nach ${DebugText.alter(it)}: ${letzter.toInt()} bpm")
            }
            setzen(stand.copy(bpm = letzter, werte = stand.werte + punkte.size, ersterWertNachMs = erster))
        }
    }

    fun starten() {
        if (stand.laeuft) return
        stand = LiveStand(laeuft = true, seit = System.currentTimeMillis())
        try {
            HealthServices.getClient(app).measureClient
                .registerMeasureCallback(DataType.HEART_RATE_BPM, rueckruf)
            DebugProtokoll.ereignis(app, "LIVE", "Test gestartet")
            setzen(stand)
        } catch (fehler: Exception) {
            DebugProtokoll.ereignis(app, "LIVE", "Start fehlgeschlagen: ${fehler.javaClass.simpleName} ${fehler.message ?: ""}")
            setzen(stand.copy(laeuft = false, fehler = fehler.javaClass.simpleName))
        }
    }

    fun stoppen() {
        if (!stand.laeuft) return
        runCatching {
            HealthServices.getClient(app).measureClient
                .unregisterMeasureCallbackAsync(DataType.HEART_RATE_BPM, rueckruf)
        }
        DebugProtokoll.ereignis(app, "LIVE", "Test beendet nach ${stand.werte} Werten")
        setzen(stand.copy(laeuft = false))
    }

    private fun setzen(neu: LiveStand) {
        stand = neu
        melden(neu)
    }
}
