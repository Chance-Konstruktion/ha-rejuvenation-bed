package net.schanz.rejuvenationbed.watch.health

import android.content.Context
import android.util.Log
import com.google.android.gms.wearable.Wearable
import net.schanz.rejuvenationbed.watch.analysis.SleepPredictionWire

/** Sends derived estimates to the paired phone only after an explicit user tap. */
object WearSleepPredictionSender {
    fun senden(context: Context, payload: String, onResult: (Result<Unit>) -> Unit) {
        val bytes = payload.toByteArray(Charsets.UTF_8)
        if (bytes.size > SleepPredictionWire.MAX_MESSAGE_BYTES) {
            onResult(Result.failure(IllegalArgumentException("Vergleichsnachricht ist zu groß")))
            return
        }
        val appContext = context.applicationContext
        Wearable.getNodeClient(appContext).connectedNodes
            .addOnSuccessListener { nodes ->
                if (nodes.isEmpty()) {
                    onResult(Result.failure(IllegalStateException("Kein gekoppeltes Smartphone verbunden")))
                    return@addOnSuccessListener
                }
                var remaining = nodes.size
                var delivered = false
                var lastError: Exception? = null
                nodes.forEach { node ->
                    Wearable.getMessageClient(appContext)
                        .sendMessage(node.id, SleepPredictionWire.MESSAGE_PATH, bytes)
                        .addOnCompleteListener { task ->
                            if (task.isSuccessful) delivered = true
                            else lastError = task.exception ?: IllegalStateException("Wear-Nachricht fehlgeschlagen")
                            remaining -= 1
                            if (remaining == 0) {
                                if (delivered) {
                                    Log.i(TAG, "Abgeleitete Schlafschätzung an gekoppeltes Smartphone gesendet")
                                    onResult(Result.success(Unit))
                                } else {
                                    onResult(Result.failure(lastError ?: IllegalStateException("Smartphone nicht erreichbar")))
                                }
                            }
                        }
                }
            }
            .addOnFailureListener { onResult(Result.failure(it)) }
    }

    private const val TAG = "BedSleepSender"
}
