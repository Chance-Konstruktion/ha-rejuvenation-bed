package net.schanz.rejuvenationbed.watch.health

import androidx.health.services.client.PassiveListenerService
import androidx.health.services.client.data.DataPointContainer
import androidx.health.services.client.data.UserActivityInfo

/**
 * Receives batched passive samples and coarse platform asleep/awake state.
 * Health Services is the only allowed binder (see the manifest permission).
 */
class PassiveHeartRateService : PassiveListenerService() {
    override fun onNewDataPointsReceived(dataPoints: DataPointContainer) {
        HeartRateSampleStore.append(applicationContext, dataPoints)
    }

    override fun onUserActivityInfoReceived(info: UserActivityInfo) {
        HeartRateSampleStore.appendUserActivity(applicationContext, info)
    }

    override fun onPermissionLost() {
        HeartRateSampleStore.setStatus(applicationContext, "permission_lost")
    }
}
