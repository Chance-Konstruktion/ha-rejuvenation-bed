package net.schanz.rejuvenationbed.phone
import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import net.schanz.rejuvenationbed.watch.analysis.SleepStageReferenceInterval
import net.schanz.rejuvenationbed.watch.sleep.SleepStage
import java.time.Instant

/** Health Connect is phone-only. Samsung Health synchronizes Galaxy Watch sleep data to the phone first. */
class HealthConnectSleepQuelle(context: Context) {
    private val appContext = context.applicationContext
    fun sdkStatus(): Int = HealthConnectClient.getSdkStatus(appContext)

    suspend fun leseSchlafphasen(startEpochMillis: Long, endEpochMillis: Long): List<SleepStageReferenceInterval> {
        require(startEpochMillis >= 0L)
        require(endEpochMillis > startEpochMillis)
        val hc = HealthConnectClient.getOrCreate(appContext)
        if (READ_SLEEP_PERMISSION !in hc.permissionController.getGrantedPermissions()) {
            throw SecurityException("Health-Connect-Leserecht READ_SLEEP fehlt")
        }
        val response = hc.readRecords(
            ReadRecordsRequest(
                recordType = SleepSessionRecord::class,
                timeRangeFilter = TimeRangeFilter.between(
                    Instant.ofEpochMilli(startEpochMillis),
                    Instant.ofEpochMilli(endEpochMillis)
                )
            )
        )
        return response.records.flatMap { session ->
            session.stages.mapNotNull { stage ->
                val mapped = when (stage.stage) {
                    SleepSessionRecord.STAGE_TYPE_AWAKE,
                    SleepSessionRecord.STAGE_TYPE_AWAKE_IN_BED,
                    SleepSessionRecord.STAGE_TYPE_OUT_OF_BED -> SleepStage.AWAKE
                    SleepSessionRecord.STAGE_TYPE_LIGHT -> SleepStage.LIGHT
                    SleepSessionRecord.STAGE_TYPE_DEEP -> SleepStage.DEEP
                    SleepSessionRecord.STAGE_TYPE_REM -> SleepStage.REM
                    else -> SleepStage.UNKNOWN
                }
                if (mapped == SleepStage.UNKNOWN) null
                else SleepStageReferenceInterval(
                    startEpochMillis = stage.startTime.toEpochMilli(),
                    endEpochMillis = stage.endTime.toEpochMilli(),
                    stage = mapped
                )
            }
        }.filter { it.endEpochMillis > startEpochMillis && it.startEpochMillis < endEpochMillis }
            .sortedBy { it.startEpochMillis }
    }

    companion object {
        val READ_SLEEP_PERMISSION: String = HealthPermission.getReadPermission(SleepSessionRecord::class)
    }
}
