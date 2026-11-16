package net.schanz.rejuvenationbed.watch.health

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/**
 * Eigene SQLite-Tabelle für den passiven Puls (#8, Ziel A), wie `ibi_sample`.
 * Die Werte bleiben auf der Uhr; kein Export, kein Netzwerk, kein Backup-Weg.
 *
 * Aufbewahrung nach ZEIT, nicht nach Anzahl: Beim Einfügen und in derselben
 * Transaktion fällt alles unterhalb der 36-h-Grenze (`PulsAufbewahrung`)
 * weg. Doppelte Zeitstempel ersetzen sich gegenseitig (PRIMARY KEY +
 * INSERT OR REPLACE), wie die Plattform sie gelegentlich doppelt bündelt.
 */
class PulsSampleSpeicher(context: Context) : SQLiteOpenHelper(
    context.applicationContext,
    DATENBANK,
    null,
    VERSION
) {
    @Synchronized
    fun einfuegen(samples: List<HeartRateSample>, jetztEpochMillis: Long = System.currentTimeMillis()) {
        if (samples.isEmpty()) return
        val untereGrenze = PulsAufbewahrung.untergrenze(jetztEpochMillis)
        writableDatabase.beginTransaction()
        try {
            val statement = writableDatabase.compileStatement(
                "INSERT OR REPLACE INTO heart_rate_sample (measured_at, bpm) VALUES (?, ?)"
            )
            samples.forEach { sample ->
                if (sample.measuredAtEpochMillis in untereGrenze..jetztEpochMillis) {
                    statement.clearBindings()
                    statement.bindLong(1, sample.measuredAtEpochMillis)
                    statement.bindDouble(2, sample.beatsPerMinute)
                    statement.executeInsert()
                }
            }
            writableDatabase.delete("heart_rate_sample", "measured_at < ?", arrayOf(untereGrenze.toString()))
            writableDatabase.setTransactionSuccessful()
        } finally {
            writableDatabase.endTransaction()
        }
    }

    @Synchronized
    fun lesen(startEpochMillis: Long, endEpochMillis: Long): List<HeartRateSample> {
        require(startEpochMillis >= 0L) { "start must be non-negative" }
        require(endEpochMillis > startEpochMillis) { "range must be positive" }
        val result = mutableListOf<HeartRateSample>()
        readableDatabase.query(
            "heart_rate_sample",
            arrayOf("measured_at", "bpm"),
            "measured_at > ? AND measured_at <= ?",
            arrayOf(startEpochMillis.toString(), endEpochMillis.toString()),
            null,
            null,
            "measured_at ASC"
        ).use { cursor ->
            while (cursor.moveToNext()) {
                result += HeartRateSample(
                    measuredAtEpochMillis = cursor.getLong(0),
                    beatsPerMinute = cursor.getDouble(1)
                )
            }
        }
        return result
    }

    /** Anzahl im aufbewahrten Fenster — fürs Debug-Blatt, ohne die Reihe zu laden. */
    @Synchronized
    fun anzahl(): Int {
        readableDatabase.rawQuery("SELECT COUNT(*) FROM heart_rate_sample", null).use { cursor ->
            return if (cursor.moveToFirst()) cursor.getInt(0) else 0
        }
    }

    /** Jüngster Wert — fürs Debug-Blatt und die Now Bar, ohne die Reihe zu laden. */
    @Synchronized
    fun juengster(): HeartRateSample? {
        readableDatabase.query(
            "heart_rate_sample",
            arrayOf("measured_at", "bpm"),
            null,
            null,
            null,
            null,
            "measured_at DESC",
            "1"
        ).use { cursor ->
            return if (cursor.moveToFirst()) {
                HeartRateSample(measuredAtEpochMillis = cursor.getLong(0), beatsPerMinute = cursor.getDouble(1))
            } else {
                null
            }
        }
    }

    @Synchronized
    fun loeschen() {
        writableDatabase.delete("heart_rate_sample", null, null)
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE heart_rate_sample (" +
                "measured_at INTEGER PRIMARY KEY, " +
                "bpm REAL NOT NULL" +
                ")"
        )
        db.execSQL("CREATE INDEX heart_rate_sample_time_idx ON heart_rate_sample(measured_at)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        // Version 1 ist die erste und einzige Tabelle. Künftige Upgrades
        // müssen Zeitstempel erhalten oder diesen privaten Puffer klar benannt leeren.
    }

    private companion object {
        const val DATENBANK = "sleep_puls_local.db"
        const val VERSION = 1
    }
}
