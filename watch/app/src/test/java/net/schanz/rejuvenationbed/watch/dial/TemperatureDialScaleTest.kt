package net.schanz.rejuvenationbed.watch.dial

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TemperatureDialScaleTest {
    @Test
    fun mapsArcEndpointsToTemperatureLimits() {
        assertEquals(24.0f, TemperatureDialScale.fromAngle(135f), 0.001f)
        assertEquals(36.0f, TemperatureDialScale.fromAngle(45f), 0.001f)
    }

    @Test
    fun mapsTopOfDialToMiddleTemperature() {
        assertEquals(30.0f, TemperatureDialScale.fromAngle(270f), 0.001f)
    }

    @Test
    fun mapsNegativeAnglesAndWrapsAcrossZero() {
        assertEquals(30.0f, TemperatureDialScale.fromAngle(-90f), 0.001f)
        assertEquals(34.0f, TemperatureDialScale.fromAngle(0f), 0.001f)
    }

    @Test
    fun bottomGapSnapsToNearestArcEnd() {
        assertEquals(36.0f, TemperatureDialScale.fromAngle(60f), 0.001f)
        assertEquals(24.0f, TemperatureDialScale.fromAngle(120f), 0.001f)
    }

    @Test
    fun snapsToHalfDegreeStepsAndClamps() {
        val value = TemperatureDialScale.fromAngle(200f)
        assertEquals(0.0f, value / 0.5f - (value / 0.5f).toInt(), 0.001f)
        assertEquals(24.0f, TemperatureDialScale.fromAngle(135f, minimum = 24f, maximum = 36f), 0.001f)
        assertEquals(36.0f, TemperatureDialScale.fromAngle(45f, minimum = 24f, maximum = 36f), 0.001f)
    }

    @Test
    fun ignoresTouchesOnCenterLabels() {
        assertNull(
            TemperatureDialScale.fromPosition(
                x = 66f,
                y = 66f,
                width = 132f,
                height = 132f
            )
        )
    }

    @Test
    fun mapsRightSidePositionOnTheDial() {
        assertEquals(
            34.0f,
            TemperatureDialScale.fromPosition(
                x = 132f,
                y = 66f,
                width = 132f,
                height = 132f
            )!!,
            0.001f
        )
    }
}
