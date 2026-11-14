package net.schanz.rejuvenationbed.watch.health

import androidx.health.services.client.data.UserActivityInfo
import androidx.health.services.client.data.UserActivityState

/**
 * Coarse state reported by Wear OS Health Services, not a sleep stage.
 * PASSIVE and EXERCISE mean awake; UNKNOWN must never be interpreted as asleep.
 */
enum class PlatformSleepState(val label: String) {
    ASLEEP("schlafend"),
    AWAKE("wach"),
    UNKNOWN("unbekannt");

    companion object {
        fun fromHealthServices(info: UserActivityInfo): PlatformSleepState =
            when (info.userActivityState) {
                UserActivityState.USER_ACTIVITY_ASLEEP -> ASLEEP
                UserActivityState.USER_ACTIVITY_PASSIVE,
                UserActivityState.USER_ACTIVITY_EXERCISE -> AWAKE
                else -> UNKNOWN
            }
    }
}

data class PlatformSleepStateEvent(
    val state: PlatformSleepState,
    val changedAtEpochMillis: Long
) {
    init {
        require(changedAtEpochMillis >= 0L) { "state change timestamp must be non-negative" }
    }

    fun isFresh(
        nowEpochMillis: Long,
        maxAgeMillis: Long = 18L * 60L * 60L * 1000L,
        futureToleranceMillis: Long = 30_000L
    ): Boolean {
        require(nowEpochMillis >= 0L) { "now must be non-negative" }
        require(maxAgeMillis >= 0L) { "maxAgeMillis must be non-negative" }
        require(futureToleranceMillis >= 0L) { "futureToleranceMillis must be non-negative" }
        return changedAtEpochMillis in (nowEpochMillis - maxAgeMillis)..(nowEpochMillis + futureToleranceMillis)
    }
}
