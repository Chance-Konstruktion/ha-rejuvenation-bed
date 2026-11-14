package net.schanz.rejuvenationbed.watch.health

import androidx.health.services.client.data.UserActivityInfo
import androidx.health.services.client.data.UserActivityState
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.Instant

class PlatformSleepStateTest {
    @Test
    fun mapsPlatformAsleepToCoarseSleepState() {
        assertEquals(PlatformSleepState.ASLEEP, map(UserActivityState.USER_ACTIVITY_ASLEEP))
    }

    @Test
    fun mapsPassiveAndExerciseToAwake() {
        assertEquals(PlatformSleepState.AWAKE, map(UserActivityState.USER_ACTIVITY_PASSIVE))
        assertEquals(PlatformSleepState.AWAKE, map(UserActivityState.USER_ACTIVITY_EXERCISE))
    }

    @Test
    fun mapsUnknownStateFailClosed() {
        assertEquals(PlatformSleepState.UNKNOWN, map(UserActivityState.USER_ACTIVITY_UNKNOWN))
    }

    @Test
    fun rejectsStaleAndFarFutureStateEvents() {
        val now = 1_800_000_000_000L
        assertEquals(true, eventAt(now - 60_000L).isFresh(now))
        assertEquals(false, eventAt(now - 19L * 60L * 60L * 1000L).isFresh(now))
        assertEquals(true, eventAt(now + 10_000L).isFresh(now))
        assertEquals(false, eventAt(now + 60_000L).isFresh(now))
    }

    private fun eventAt(timestamp: Long) =
        PlatformSleepStateEvent(PlatformSleepState.ASLEEP, timestamp)

    private fun map(state: UserActivityState): PlatformSleepState =
        PlatformSleepState.fromHealthServices(UserActivityInfo(state, null, Instant.ofEpochMilli(1_800_000_000_000L)))
}
