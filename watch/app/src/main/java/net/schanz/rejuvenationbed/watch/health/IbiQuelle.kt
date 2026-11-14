package net.schanz.rejuvenationbed.watch.health

/**
 * One inter-beat interval reported by a watch sensor.
 *
 * [measuredAtEpochMillis] is the timestamp of the beat ending this interval.
 * [signalQuality] is optional because not every provider exposes a quality score.
 */
data class IbiMesspunkt(
    val measuredAtEpochMillis: Long,
    val intervalMillis: Double,
    val signalQuality: Double? = null
) {
    init {
        require(measuredAtEpochMillis >= 0L) { "timestamp must be non-negative" }
        require(intervalMillis.isFinite()) { "IBI must be finite" }
        require(signalQuality == null || (signalQuality.isFinite() && signalQuality in 0.0..1.0)) {
            "signalQuality must be null or between 0 and 1"
        }
    }
}

sealed interface IbiQuelleStatus {
    data object Verfuegbar : IbiQuelleStatus
    data class NichtVerfuegbar(val grund: String) : IbiQuelleStatus
}

sealed interface IbiStartErgebnis {
    data object Gestartet : IbiStartErgebnis
    data class NichtVerfuegbar(val grund: String) : IbiStartErgebnis
    data class Fehlgeschlagen(val grund: String) : IbiStartErgebnis
}

fun interface IbiEmpfaenger {
    fun beiMesspunkt(messpunkt: IbiMesspunkt)
}

/**
 * Replaceable IBI provider boundary. Implementations must never upload samples.
 * The UI owns explicit start/stop and permission handling.
 */
interface IbiQuelle {
    val name: String
    fun status(): IbiQuelleStatus
    fun starten(empfaenger: IbiEmpfaenger): IbiStartErgebnis
    fun stoppen()
}

/**
 * Narrow bridge implemented by the optional Samsung AAR integration.
 * Keeping Samsung API types out of this module lets the app build without the
 * account-distributed SDK and makes the boundary testable.
 */
interface SamsungHealthSensorSdkBruecke {
    fun status(): IbiQuelleStatus
    fun starten(empfaenger: IbiEmpfaenger): IbiStartErgebnis
    fun stoppen()
}

/**
 * Production adapter. A null bridge is the explicitly named SDK gap: Samsung's
 * AAR is not vendored in this repository, so IBI capture fails closed.
 */
class SamsungHealthSensorSdkIbiQuelle(
    private val bruecke: SamsungHealthSensorSdkBruecke? = null
) : IbiQuelle {
    override val name: String = "Samsung Health Sensor SDK"

    override fun status(): IbiQuelleStatus =
        bruecke?.status() ?: IbiQuelleStatus.NichtVerfuegbar(
            "Samsung-AAR fehlt; siehe docs/IBI_ADAPTER.md"
        )

    override fun starten(empfaenger: IbiEmpfaenger): IbiStartErgebnis =
        when (val verfuegbarkeit = status()) {
            IbiQuelleStatus.Verfuegbar -> bruecke?.starten(empfaenger)
                ?: IbiStartErgebnis.NichtVerfuegbar("Samsung-Bruecke fehlt")
            is IbiQuelleStatus.NichtVerfuegbar -> IbiStartErgebnis.NichtVerfuegbar(verfuegbarkeit.grund)
        }

    override fun stoppen() {
        bruecke?.stoppen()
    }
}

/** Deterministic source for unit tests and repeatable offline experiments. */
class FakeIbiQuelle(
    private val messpunkte: List<IbiMesspunkt>,
    private val verfuegbar: Boolean = true
) : IbiQuelle {
    override val name: String = "Fake-IBI"
    private var aktiv = false

    override fun status(): IbiQuelleStatus =
        if (verfuegbar) IbiQuelleStatus.Verfuegbar
        else IbiQuelleStatus.NichtVerfuegbar("Fake-Quelle deaktiviert")

    override fun starten(empfaenger: IbiEmpfaenger): IbiStartErgebnis {
        if (!verfuegbar) return IbiStartErgebnis.NichtVerfuegbar("Fake-Quelle deaktiviert")
        aktiv = true
        messpunkte.forEach { if (aktiv) empfaenger.beiMesspunkt(it) }
        return IbiStartErgebnis.Gestartet
    }

    override fun stoppen() {
        aktiv = false
    }
}
