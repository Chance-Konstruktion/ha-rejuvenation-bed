package net.schanz.rejuvenationbed.watch.health

import android.content.Context
import androidx.health.services.client.HealthServices
import androidx.health.services.client.data.DataType
import androidx.health.services.client.data.PassiveListenerConfig

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
            onComplete(Result.failure(error))
            return
        }

        future.addListener(
            {
                val result = runCatching {
                    future.get()
                    HeartRateSampleStore.markRegistered(appContext)
                }
                if (result.isFailure) {
                    HeartRateSampleStore.setStatus(appContext, "registration_failed")
                }
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
                onComplete(result)
            },
            appContext.mainExecutor
        )
    }
}
