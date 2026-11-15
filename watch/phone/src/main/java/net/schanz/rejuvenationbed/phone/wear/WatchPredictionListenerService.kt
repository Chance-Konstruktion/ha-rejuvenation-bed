package net.schanz.rejuvenationbed.phone.wear
import android.util.Log
import com.google.android.gms.wearable.MessageEvent
import com.google.android.gms.wearable.WearableListenerService
import net.schanz.rejuvenationbed.phone.WatchPredictionPayload
import net.schanz.rejuvenationbed.watch.analysis.SleepPredictionWire

/** Receives derived stages only, never IBI, BPM, steps or Health Connect records. */
class WatchPredictionListenerService : WearableListenerService() {
    override fun onMessageReceived(messageEvent: MessageEvent) {
        if (messageEvent.path != SleepPredictionWire.MESSAGE_PATH) {
            super.onMessageReceived(messageEvent)
            return
        }
        if (messageEvent.data.size > SleepPredictionWire.MAX_MESSAGE_BYTES) {
            Log.w(TAG, "Watch-Vergleichsdaten verworfen: Nachricht zu groß")
            return
        }
        val json = messageEvent.data.toString(Charsets.UTF_8)
        val payload = runCatching { WatchPredictionPayload.decode(json) }
            .onFailure {
                Log.w(TAG, "Watch-Vergleichsdaten verworfen: ungültiger Vertrag (${it.javaClass.simpleName})")
            }.getOrNull() ?: return
        getSharedPreferences(SleepPredictionWire.PHONE_PREFERENCES, MODE_PRIVATE)
            .edit()
            .putString(SleepPredictionWire.PHONE_PAYLOAD_KEY, json)
            .putLong("received_at", System.currentTimeMillis())
            .putString("source_node_id", messageEvent.sourceNodeId)
            .commit()
        Log.i(TAG, "Abgeleitete Schlafphasen empfangen (${payload.predictions.size} Werte)")
    }
    companion object { private const val TAG = "BedSleepValidation" }
}
