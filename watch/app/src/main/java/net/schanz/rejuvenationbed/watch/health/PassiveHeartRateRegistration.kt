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
                }
                if (result.isFailure) {
                    HeartRateSampleStore.setStatus(appContext, "registration_failed")
                }
                DebugProtokoll.ereignis(
                    appContext, "REG",
                    result.exceptionOrNull()?.let { "Registrierung fehlgeschlagen: ${it.javaClass.simpleName} ${it.message ?: ""}" }
                        ?: "Registrierung bestätigt"
                )
                onComplete(result)
            },
            appContext.mainExecutor
        )
    }

    fun stop(context: Context, onComplete: (Result<Unit>) -> Unit) {
        val appContext = context.applicationContext
        // Disable writes immediately; a late callback must not repopulate deleted data.
        HeartRateSampleStore.clear(appContext)
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
                    result.exceptionOrNull()?.let { "Stopp fehlgeschlagen: ${it.javaClass.simpleName}" } ?: "gestoppt, Daten gelöscht"
                )
                onComplete(result)
            },
            appContext.mainExecutor
        )
    }
}
