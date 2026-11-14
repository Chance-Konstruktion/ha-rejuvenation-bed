package net.schanz.rejuvenationbed.watch.health

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build

/**
 * Wear OS uses legacy BODY_SENSORS permissions through API 35 and granular
 * android.permission.health permissions on API 36+. Passive steps and
 * platform sleep/wake state use ACTIVITY_RECOGNITION.
 */
object WearHealthPermissions {
    fun heartRatePermission(): String =
        if (Build.VERSION.SDK_INT >= 36) {
            "android.permission.health.READ_HEART_RATE"
        } else {
            Manifest.permission.BODY_SENSORS
        }

    fun backgroundHeartRatePermission(): String? =
        when {
            Build.VERSION.SDK_INT >= 36 -> "android.permission.health.READ_HEALTH_DATA_IN_BACKGROUND"
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU -> Manifest.permission.BODY_SENSORS_BACKGROUND
            else -> null
        }

    fun firstMissingPermission(context: Context, needsActivityRecognition: Boolean): String? {
        val heartRate = heartRatePermission()
        if (!isGranted(context, heartRate)) return heartRate

        val background = backgroundHeartRatePermission()
        if (background != null && !isGranted(context, background)) return background

        if (needsActivityRecognition && !isGranted(context, Manifest.permission.ACTIVITY_RECOGNITION)) {
            return Manifest.permission.ACTIVITY_RECOGNITION
        }

        return null
    }

    fun isGranted(context: Context, permission: String): Boolean =
        context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
}
