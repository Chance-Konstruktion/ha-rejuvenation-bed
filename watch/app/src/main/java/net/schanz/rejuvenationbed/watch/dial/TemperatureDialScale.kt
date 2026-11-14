package net.schanz.rejuvenationbed.watch.dial

import kotlin.math.atan2
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Maps touches on the 270-degree ring to half-degree temperature steps.
 * The inactive 90-degree section is at the bottom of the watch face.
 */
object TemperatureDialScale {
    fun fromPosition(
        x: Float,
        y: Float,
        width: Float,
        height: Float,
        minimum: Float = 24.0f,
        maximum: Float = 36.0f,
        step: Float = 0.5f
    ): Float? {
        require(width > 0f && height > 0f) { "dial dimensions must be positive" }
        require(minimum < maximum) { "minimum must be below maximum" }
        require(step > 0f) { "step must be positive" }

        val dx = x - width / 2f
        val dy = y - height / 2f
        val radius = min(width, height) / 2f

        // Ignore the centre labels. Only the surrounding touch ring adjusts temperature.
        if (kotlin.math.sqrt(dx * dx + dy * dy) < radius * 0.35f) {
            return null
        }

        val angle = Math.toDegrees(atan2(dy.toDouble(), dx.toDouble())).toFloat()
        return fromAngle(angle, minimum, maximum, step)
    }

    fun fromAngle(
        angleDegrees: Float,
        minimum: Float = 24.0f,
        maximum: Float = 36.0f,
        step: Float = 0.5f
    ): Float {
        require(minimum < maximum) { "minimum must be below maximum" }
        require(step > 0f) { "step must be positive" }

        val angle = ((angleDegrees % 360f) + 360f) % 360f
        // Arc starts at 135° (bottom-left) and ends at 45° (bottom-right).
        val activeAngle = when {
            angle >= 135f -> angle
            angle <= 45f -> angle + 360f
            angle - 45f < 135f - angle -> 405f
            else -> 135f
        }

        val progress = ((activeAngle - 135f) / 270f).coerceIn(0f, 1f)
        val raw = minimum + (maximum - minimum) * progress
        val snapped = minimum + ((raw - minimum) / step).roundToInt() * step
        return snapped.coerceIn(minimum, maximum)
    }
}
