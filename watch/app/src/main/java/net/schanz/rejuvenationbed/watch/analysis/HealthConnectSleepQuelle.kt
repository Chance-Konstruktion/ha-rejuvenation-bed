package net.schanz.rejuvenationbed.watch.analysis

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import net.schanz.rejuvenationbed.watch.sleep.SleepStage
import java.time.Instant
import kotlin.reflect.KClass

/**
 * Explicit, read-only Health Connect reference reader.
 * It never writes estimated stages back to Health Connect.
 */
class HealthConnectSleepQuelle(context: Context) {
    private val client = HealthConnectClient.getOrCreate(context.applicationContext)

    suspend fun readSleepStages(
        startEpochMillis: Long,
        endEpochMillis: Long
    ): List<SleepStageReferenceInterval> {
        require(startEpochMillis >= 0L)
        require(endEpochMillis > startEpochMillis)

        val permission = HealthPermission.getReadPermission(SleepSessionRecord::class)
        if (permission !in client.permissionController.getGrantedPermissions()) {
            throw SecurityException("Health-Connect-Berechtigung READ_SLEEP fehlt")
        }

        val response = client.readRecords(
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
                val mapped = mapStage(stage.stage)
                if (mapped == SleepStage.UNKNOWN) null
                else SleepStageReferenceInterval(
                    startEpochMillis = stage.startTime.toEpochMilli(),
                    endEpochMillis = stage.endTime.toEpochMilli(),
                    stage = mapped
                )
            }
        }.filter {
            it.endEpochMillis > startEpochMillis && it.startEpochMillis < endEpochMillis
        }.sortedBy { it.startEpochMillis }
    }

    private fun mapStage(value: Int): SleepStage = when (value) {
        SleepSessionRecord.STAGE_TYPE_AWAKE,
        SleepSessionRecord.STAGE_TYPE_AWAKE_IN_BED,
        SleepSessionRecord.STAGE_TYPE_OUT_OF_BED -> SleepStage.AWAKE
        SleepSessionRecord.STAGE_TYPE_LIGHT -> SleepStage.LIGHT
        SleepSessionRecord.STAGE_TYPE_DEEP -> SleepStage.DEEP
        SleepSessionRecord.STAGE_TYPE_REM -> SleepStage.REM
        else -> SleepStage.UNKNOWN
    }
}
