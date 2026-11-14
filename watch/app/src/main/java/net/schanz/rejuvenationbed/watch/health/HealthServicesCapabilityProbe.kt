package net.schanz.rejuvenationbed.watch.health

import android.content.Context
import androidx.health.services.client.HealthServices
import androidx.health.services.client.data.DataType
import androidx.health.services.client.data.UserActivityState

sealed interface HeartRateCapability {
    data object Checking : HeartRateCapability
    data object Supported : HeartRateCapability
    data object Unsupported : HeartRateCapability
    data class Failed(val reason: String) : HeartRateCapability
}

/**
 * Checks this exact watch before requesting passive data.
 * Capabilities are not a claim that permission is granted or samples are arriving.
 */
object HealthServicesCapabilityProbe {
    fun check(
        context: Context,
        onResult: (HeartRateCapability, Boolean, Boolean) -> Unit
    ) {
        val appContext = context.applicationContext
        val future = try {
            HealthServices.getClient(appContext).passiveMonitoringClient.getCapabilitiesAsync()
        } catch (error: Exception) {
            onResult(HeartRateCapability.Failed(error.javaClass.simpleName), false, false)
            return
        }

        future.addListener(
            {
                try {
                    val capabilities = future.get()
                    val supportedDataTypes = capabilities.supportedDataTypesPassiveMonitoring
                    val supportedActivityStates = capabilities.supportedUserActivityStates
                    onResult(
                        if (DataType.HEART_RATE_BPM in supportedDataTypes) {
                            HeartRateCapability.Supported
                        } else {
                            HeartRateCapability.Unsupported
                        },
                        DataType.STEPS in supportedDataTypes,
                        UserActivityState.USER_ACTIVITY_ASLEEP in supportedActivityStates
                    )
                } catch (error: Exception) {
                    onResult(HeartRateCapability.Failed(error.javaClass.simpleName), false, false)
                }
            },
            appContext.mainExecutor
        )
    }
}
