package net.schanz.rejuvenationbed.watch.health

import androidx.health.services.client.PassiveListenerService
import androidx.health.services.client.data.DataPointContainer
import androidx.health.services.client.data.UserActivityInfo
import net.schanz.rejuvenationbed.watch.debug.DebugProtokoll
import net.schanz.rejuvenationbed.watch.debug.DebugText
import net.schanz.rejuvenationbed.watch.nowbar.NowBar
import net.schanz.rejuvenationbed.watch.nowbar.NowBarText

/**
 * Receives batched passive samples and coarse platform asleep/awake state.
 * Health Services is the only allowed binder (see the manifest permission).
 * Every delivery is summarised in the on-watch debug protocol.
 */
class PassiveHeartRateService : PassiveListenerService() {
    override fun onNewDataPointsReceived(dataPoints: DataPointContainer) {
        val annahme = HeartRateSampleStore.append(applicationContext, dataPoints)
        val text = if (annahme.grund != null) {
            "verworfen (${annahme.grund}): roh Puls ${annahme.rohPuls} · Schritte ${annahme.rohSchritte}"
        } else {
            DebugText.lieferung(annahme.puls, annahme.schritte, System.currentTimeMillis()) +
                " (roh ${annahme.rohPuls}/${annahme.rohSchritte})"
        }
        DebugProtokoll.ereignis(applicationContext, "DATEN", text)
        annahme.puls.lastOrNull()?.let { NowBar.aktualisieren(applicationContext, NowBarText.puls(it.beatsPerMinute)) }
    }

    override fun onUserActivityInfoReceived(info: UserActivityInfo) {
        val grund = HeartRateSampleStore.appendUserActivity(applicationContext, info)
        val zustand = PlatformSleepState.fromHealthServices(info)
        DebugProtokoll.ereignis(
            applicationContext, "PLATT",
            "${info.userActivityState} → ${zustand.label}, Wechsel " +
                DebugProtokoll.zeit(info.stateChangeTime.toEpochMilli()) +
                (grund?.let { " · verworfen: $it" } ?: "")
        )
    }

    override fun onPermissionLost() {
        HeartRateSampleStore.setStatus(applicationContext, "permission_lost")
        DebugProtokoll.ereignis(applicationContext, "RECHT", "Health Services meldet: Recht verloren")
        NowBar.stoppen(applicationContext)
    }
}
