package net.schanz.rejuvenationbed.phone

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.SleepSessionRecord
import kotlinx.coroutines.launch
import net.schanz.rejuvenationbed.watch.analysis.SleepPredictionWire
import net.schanz.rejuvenationbed.watch.analysis.SleepStageAgreement
import java.util.Locale

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { SchlafAbgleichApp() }
    }
}

@Composable
private fun SchlafAbgleichApp() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val reader = remember(context) { HealthConnectSleepQuelle(context) }
    val prefs = remember(context) {
        context.getSharedPreferences(SleepPredictionWire.PHONE_PREFERENCES, android.content.Context.MODE_PRIVATE)
    }
    var status by remember {
        mutableStateOf("Health Connect liegt auf dem Smartphone. Die Watch sendet nur abgeleitete Schätzungen.")
    }
    var resultText by remember { mutableStateOf("Noch kein Abgleich ausgeführt.") }
    var empfangText by remember {
        mutableStateOf(
            prefs.getLong("received_at", 0L).takeIf { it > 0L }
                ?.let { "Letzter Watch-Empfang: ${java.time.Instant.ofEpochMilli(it)}" }
                ?: "Noch keine Watch-Daten empfangen."
        )
    }
    var matrixRows by remember { mutableStateOf(emptyList<String>()) }

    val requiredPermissions = remember {
        setOf(HealthPermission.getReadPermission(SleepSessionRecord::class))
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        contract = PermissionController.createRequestPermissionResultContract()
    ) { granted ->
        status = if (granted.containsAll(requiredPermissions)) {
            "READ_SLEEP freigegeben. Du kannst den lokalen Abgleich starten."
        } else {
            "READ_SLEEP wurde nicht vollständig freigegeben. Der Vergleich bleibt deaktiviert."
        }
    }

    MaterialTheme {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Text("Schlafphasen-Abgleich", style = MaterialTheme.typography.headlineSmall)
                Text(status, style = MaterialTheme.typography.bodyMedium)
                Text(empfangText, style = MaterialTheme.typography.bodySmall)
                Button(
                    onClick = {
                        when (reader.sdkStatus()) {
                            HealthConnectClient.SDK_UNAVAILABLE -> status =
                                "Health Connect ist auf diesem Smartphone nicht verfügbar."
                            HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> status =
                                "Health Connect muss auf diesem Smartphone aktualisiert werden."
                            else -> permissionLauncher.launch(requiredPermissions)
                        }
                    },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Health-Connect-Leserecht anfordern")
                }
                Button(
                    onClick = {
                        scope.launch {
                            status = "Referenzdaten und Watch-Schätzungen werden lokal verglichen …"
                            try {
                                val raw = prefs.getString(SleepPredictionWire.PHONE_PAYLOAD_KEY, null)
                                    ?: throw IllegalStateException("Noch keine Watch-Schätzung empfangen")
                                val payload = WatchPredictionPayload.decode(raw)
                                val empfangen = prefs.getLong("received_at", 0L)
                                empfangText = if (empfangen > 0L) {
                                    "Letzter Watch-Empfang: ${java.time.Instant.ofEpochMilli(empfangen)}"
                                } else {
                                    "Empfangszeit nicht bekannt."
                                }
                                val healthConnect = HealthConnectClient.getOrCreate(context)
                                if (HealthConnectSleepQuelle.READ_SLEEP_PERMISSION !in
                                    healthConnect.permissionController.getGrantedPermissions()
                                ) {
                                    throw SecurityException("READ_SLEEP fehlt")
                                }
                                val references = reader.leseSchlafphasen(
                                    payload.startEpochMillis,
                                    payload.endEpochMillis
                                )
                                val agreement = SleepStageAgreement.compare(
                                    predictions = payload.predictions,
                                    references = references,
                                    startEpochMillis = payload.startEpochMillis,
                                    endEpochMillis = payload.endEpochMillis,
                                    bucketMillis = SleepPredictionWire.COMPARISON_BUCKET_MILLIS,
                                    maximumPredictionAgeMillis = SleepPredictionWire.MAX_PREDICTION_AGE_MILLIS
                                )
                                resultText = buildString {
                                    append("Algorithmus: ${payload.algorithmVersion}\n")
                                    append("Schätzungen: ${payload.predictions.size} · Referenzsegmente: ${references.size}\n")
                                    append("Verglichene 5-Minuten-Fenster: ${agreement.comparedWindows}\n")
                                    append("Accuracy: ${agreement.accuracy?.let { String.format(Locale.US, "%.1f %%", it * 100.0) } ?: "—"}\n")
                                    append("Cohen-Kappa: ${agreement.cohensKappa?.let { String.format(Locale.US, "%.3f", it) } ?: "—"}")
                                }
                                matrixRows = SleepStageAgreement.labels.map { actual ->
                                    val cells = SleepStageAgreement.labels.joinToString(" / ") { predicted ->
                                        "${predicted.wireValue}:${agreement.confusionMatrix.getValue(actual).getValue(predicted)}"
                                    }
                                    "${actual.wireValue} → $cells"
                                }
                                status = "Abgleich ausschließlich lokal auf diesem Smartphone abgeschlossen."
                            } catch (error: Exception) {
                                status = "Abgleich nicht möglich: ${error.message ?: error.javaClass.simpleName}"
                                resultText = "Kein belastbares Ergebnis."
                                matrixRows = emptyList()
                            }
                        }
                    },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text("Empfangene Schätzung lokal abgleichen")
                }
                Text(resultText, style = MaterialTheme.typography.bodyMedium)
                if (matrixRows.isNotEmpty()) {
                    Text("Konfusionsmatrix · Zeile = Referenz, Spalte = Schätzung")
                    matrixRows.forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                }
                Spacer(Modifier.height(8.dp))
                Text(
                    "Datengrenze: Nur Phasen, Konfidenz und Zeitstempel kommen von der Watch. " +
                        "IBI-Rohwerte bleiben auf der Uhr; Health-Connect-Referenzen bleiben auf diesem Smartphone. " +
                        "Es gibt keinen Upload.",
                    style = MaterialTheme.typography.bodySmall
                )
            }
        }
    }
}
