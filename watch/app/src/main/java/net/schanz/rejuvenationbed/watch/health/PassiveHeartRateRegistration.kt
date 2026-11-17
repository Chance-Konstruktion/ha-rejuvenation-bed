package net.schanz.rejuvenationbed.watch.health

import android.content.Context
import androidx.health.services.client.HealthServices
import androidx.health.services.client.data.DataType
import androidx.health.services.client.data.PassiveListenerConfig
import net.schanz.rejuvenationbed.watch.debug.DebugProtokoll

object PassiveHeartRateRegistration {
    fun start(
        context: Context,
        includeSteps: Boolean,
        includeUserActivityInfo: Boolean,
        onComplete: (Result<Unit>) -> Unit
    ) {
        val appContext = context.applicationContext
        val requestedDataTypes = if (includeSteps) {
            setOf(DataType.HEART_RATE_BPM, DataType.STEPS)
        } else {
            setOf(DataType.HEART_RATE_BPM)
        }
        val config = PassiveListenerConfig.builder()
            .setDataTypes(requestedDataTypes)
            .setShouldUserActivityInfoBeRequested(includeUserActivityInfo)
            .build()

        val future = try {
            HealthServices.getClient(appContext)
                .passiveMonitoringClient
                .setPassiveListenerServiceAsync(PassiveHeartRateService::class.java, config)
        } catch (error: Exception) {
            HeartRateSampleStore.setStatus(appContext, "registration_failed")
            DebugProtokoll.ereignis(appContext, "REG", "Start fehlgeschlagen: ${error.javaClass.simpleName} ${error.message ?: ""}")
            onComplete(Result.failure(error))
            return
        }
        DebugProtokoll.ereignis(
            appContext, "REG",
            "Start angefragt: ${requestedDataTypes.joinToString { it.name }}, Aktivität=$includeUserActivityInfo"
        )

        future.addListener(
            {
                val result = runCatching {
                    future.get()
                    HeartRateSampleStore.markRegistered(appContext)
                    // Anker für Nacht-Kennung und Zeitleiste der HA-Übertragung.
                    net.schanz.rejuvenationbed.watch.ha.HaUebertragungsEinstellungen.setzeMessungStart(
                        appContext,
                        System.currentTimeMillis()
                    )
                }
                if (result.isFailure) {
                    HeartRateSampleStore.setStatus(appContext, "registration_failed")
                }
                DebugProtokoll.ereignis(
                    appContext, "REG",
                    result.exceptionOrNull()?.let { "Registrierung fehlgeschlagen: ${it.javaClass.simpleName} ${it.message ?: ""}" }
                        ?: "Registrierung bestätigt"
                )
                // Benannter Status der IBI-Quelle, kein stiller Leerlauf (#8):
                // Das Protokoll soll jederzeit zeigen, warum Phasen (oder deren
                // Ersatz) aus welcher Quelle kommen oder fehlen.
                runCatching {
                    val ibiQuelle = SamsungHealthSensorSdkIbiQuelle()
                    val stand = when (val status = ibiQuelle.status()) {
                        IbiQuelleStatus.Verfuegbar -> "verfügbar"
                        is IbiQuelleStatus.NichtVerfuegbar -> "nicht verfügbar: ${status.grund}"
                    }
                    DebugProtokoll.ereignis(
                        appContext, "IBI",
                        "Quelle ${ibiQuelle.name}: $stand — ohne IBI nur grobe Puls+Bewegungs-Schätzung"
                    )
                }
                onComplete(result)
            },
            appContext.mainExecutor
        )
    }

    fun stop(context: Context, onComplete: (Result<Unit>) -> Unit) {
        val appContext = context.applicationContext
        // Disable writes immediately; recorded data stays (#7).
        HeartRateSampleStore.stopWriting(appContext)
        val future = try {
            HealthServices.getClient(appContext)
                .passiveMonitoringClient
                .clearPassiveListenerServiceAsync()
        } catch (error: Exception) {
            HeartRateSampleStore.setStatus(appContext, "stop_failed")
            onComplete(Result.failure(error))
            return
        }

        future.addListener(
            {
                val result = runCatching {
                    future.get()
                    HeartRateSampleStore.setStatus(appContext, "stopped")
                }
                if (result.isFailure) HeartRateSampleStore.setStatus(appContext, "stop_failed")
                DebugProtokoll.ereignis(
                    appContext, "REG",
                    result.exceptionOrNull()?.let { "Stopp fehlgeschlagen: ${it.javaClass.simpleName}" } ?: "gestoppt, Daten behalten (Puls ${HeartRateSampleStore.sampleCount(appContext)}, Schritte ${HeartRateSampleStore.stepIntervalCount(appContext)})"
                )
                if (result.isSuccess) {
                    // Nacht ist abgeschlossen: Bericht (und in „Gesamtdaten“ die
                    // Messreihen-Pakete) anstellen und über den lokalen Webhook
                    // versuchen. Läuft im eigenen Hintergrund-Faden, nicht hier.
                    net.schanz.rejuvenationbed.watch.ha.HaUebertragung.nachStopp(appContext)
                }
                onComplete(result)
            },
            appContext.mainExecutor
        )
    }
}
