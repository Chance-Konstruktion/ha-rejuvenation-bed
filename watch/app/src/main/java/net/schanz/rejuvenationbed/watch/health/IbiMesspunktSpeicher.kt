package net.schanz.rejuvenationbed.watch.health

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/**
 * Small private SQLite ring for IBI values. Data stays on the watch; no export,
 * network transport or backup path is provided. The caller must start capture
 * only after an explicit user action and required sensor permission.
 */
class IbiMesspunktSpeicher(context: Context) : SQLiteOpenHelper(
    context.applicationContext,
    DATABASE_NAME,
    null,
    DATABASE_VERSION
) {
    @Synchronized
    fun speichernAlle(messpunkte: List<IbiMesspunkt>, jetztEpochMillis: Long = System.currentTimeMillis()) {
        if (messpunkte.isEmpty()) return
        val cutoff = jetztEpochMillis - MAX_AGE_MILLIS
        writableDatabase.beginTransaction()
        try {
            val statement = writableDatabase.compileStatement(
                "INSERT OR REPLACE INTO ibi_sample (measured_at, interval_ms, signal_quality) VALUES (?, ?, ?)"
            )
            messpunkte.forEach { sample ->
                if (sample.measuredAtEpochMillis in cutoff..jetztEpochMillis) {
                    statement.clearBindings()
                    statement.bindLong(1, sample.measuredAtEpochMillis)
                    statement.bindDouble(2, sample.intervalMillis)
                    if (sample.signalQuality == null) statement.bindNull(3)
                    else statement.bindDouble(3, sample.signalQuality)
                    statement.executeInsert()
                }
            }
            writableDatabase.delete("ibi_sample", "measured_at < ?", arrayOf(cutoff.toString()))
            writableDatabase.execSQL(
                "DELETE FROM ibi_sample WHERE measured_at NOT IN " +
                    "(SELECT measured_at FROM ibi_sample ORDER BY measured_at DESC LIMIT $MAX_SAMPLES)"
            )
            writableDatabase.setTransactionSuccessful()
        } finally {
            writableDatabase.endTransaction()
        }
    }

    @Synchronized
    fun lesen(startEpochMillis: Long, endEpochMillis: Long): List<IbiMesspunkt> {
        require(startEpochMillis >= 0L)
        require(endEpochMillis > startEpochMillis)
        val result = mutableListOf<IbiMesspunkt>()
        readableDatabase.query(
            "ibi_sample",
            arrayOf("measured_at", "interval_ms", "signal_quality"),
            "measured_at > ? AND measured_at <= ?",
            arrayOf(startEpochMillis.toString(), endEpochMillis.toString()),
            null,
            null,
            "measured_at ASC"
        ).use { cursor ->
            while (cursor.moveToNext()) {
                result += IbiMesspunkt(
                    measuredAtEpochMillis = cursor.getLong(0),
                    intervalMillis = cursor.getDouble(1),
                    signalQuality = if (cursor.isNull(2)) null else cursor.getDouble(2)
                )
            }
        }
        return result
    }

    @Synchronized
    fun loeschen() {
        writableDatabase.delete("ibi_sample", null, null)
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE ibi_sample (" +
                "measured_at INTEGER PRIMARY KEY, " +
                "interval_ms REAL NOT NULL, " +
                "signal_quality REAL)"
        )
        db.execSQL("CREATE INDEX ibi_sample_time_idx ON ibi_sample(measured_at)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        // Version 1 is intentionally the first and only stored schema.
        // Future upgrades must preserve timestamps or explicitly clear this private cache.
    }

    private companion object {
        const val DATABASE_NAME = "sleep_ibi_local.db"
        const val DATABASE_VERSION = 1
        const val MAX_AGE_MILLIS = 10L * 60L * 60L * 1000L
        const val MAX_SAMPLES = 40_000
    }
}

/** Connects a chosen provider to the private store; still no transport or upload. */
class IbiMessungSteuerung(
    context: Context,
    private val quelle: IbiQuelle
) {
    private val speicher = IbiMesspunktSpeicher(context.applicationContext)

    fun status(): IbiQuelleStatus = quelle.status()

    fun starten(): IbiStartErgebnis = quelle.starten(
        IbiEmpfaenger { sample -> speicher.speichernAlle(listOf(sample)) }
    )

    fun stoppen() {
        quelle.stoppen()
    }

    fun fensterLesen(startEpochMillis: Long, endEpochMillis: Long): List<IbiMesspunkt> =
        speicher.lesen(startEpochMillis, endEpochMillis)

    fun datenLoeschen() {
        stoppen()
        speicher.loeschen()
    }
}
