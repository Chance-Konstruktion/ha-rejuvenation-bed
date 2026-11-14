package net.schanz.rejuvenationbed.watch

import android.content.Context
import android.content.SharedPreferences
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.Text
import net.schanz.rejuvenationbed.watch.analysis.SleepFeatureExtractor
import net.schanz.rejuvenationbed.watch.analysis.SleepFeatureWindow
import net.schanz.rejuvenationbed.watch.dial.TemperatureDialScale
import net.schanz.rejuvenationbed.watch.health.HeartRateCapability
import net.schanz.rejuvenationbed.watch.health.HealthServicesCapabilityProbe
import net.schanz.rejuvenationbed.watch.health.HeartRateSampleStore
import net.schanz.rejuvenationbed.watch.health.PassiveHeartRateRegistration
import net.schanz.rejuvenationbed.watch.health.PlatformSleepState
import net.schanz.rejuvenationbed.watch.health.PlatformSleepStateEvent
import net.schanz.rejuvenationbed.watch.health.WearHealthPermissions
import java.util.Locale
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

private val Amber = Color(0xFFE5A23B)
private val Midnight = Color(0xFF050505)
private val Muted = Color(0xFF9B958B)
private const val MIN_BED_TEMPERATURE = 24.0f
private const val MAX_BED_TEMPERATURE = 36.0f

@Composable
fun WatchHomeScreen() {
    // This state is a visual-only preview until the HA client is implemented.
    var previewTarget by remember { mutableFloatStateOf(29.0f) }
    val pagerState = rememberPagerState(pageCount = { 2 })

    HorizontalPager(
        state = pagerState,
        modifier = Modifier
            .fillMaxSize()
            .background(Midnight)
    ) { page ->
        when (page) {
            0 -> SleepPage()
            1 -> ThermostatPage(
                targetTemperature = previewTarget,
                onTemperatureChange = { previewTarget = it }
            )
        }
    }
}

@Composable
private fun SleepPage() {
    val context = LocalContext.current
    var heartRateCapability by remember { mutableStateOf<HeartRateCapability>(HeartRateCapability.Checking) }
    var stepsSupported by remember { mutableStateOf(false) }
    var sleepStateSupported by remember { mutableStateOf(false) }
    var permissionVersion by remember { mutableIntStateOf(0) }
    var sensorMessage by remember { mutableStateOf("Noch nicht aktiviert") }
    var registrationBusy by remember { mutableStateOf(false) }

    LaunchedEffect(context) {
        HealthServicesCapabilityProbe.check(context.applicationContext) { result, supportsSteps, supportsSleepState ->
            heartRateCapability = result
            stepsSupported = supportsSteps
            sleepStateSupported = supportsSleepState
        }
    }

    // Re-check OS permissions whenever a runtime permission dialog closes.
    val missingPermission = remember(permissionVersion, stepsSupported, sleepStateSupported) {
        WearHealthPermissions.firstMissingPermission(context, needsActivityRecognition = stepsSupported || sleepStateSupported)
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted ->
        permissionVersion += 1
        sensorMessage = if (granted) {
            "Berechtigung erteilt · nächster Schritt"
        } else {
            "Berechtigung nicht erteilt"
        }
    }

    val localSnapshot = rememberLocalSleepSnapshot(context)
    val collectionStatus = localSnapshot.collectionStatus
    val backgroundActive = collectionStatus == "registered" || collectionStatus == "collecting"
    val latestWindow = localSnapshot.windows.lastOrNull { it.heartRateSampleCount > 0 }
    val featureWindowCount = localSnapshot.windows.count { it.hasMinimumHeartRateFeatures }
    val platformSleepLabel = localSnapshot.platformSleepState?.let { it.state.label }

    LaunchedEffect(collectionStatus) {
        sensorMessage = when (collectionStatus) {
            "registered" -> "Hintergrundmessung aktiv · wartet auf Werte"
            "collecting" -> "Messpunkte werden lokal gespeichert"
            "permission_lost" -> "Berechtigung verloren · bitte erneut aktivieren"
            "registration_failed" -> "Aktivierung fehlgeschlagen"
            "stopped" -> "Messung beendet · lokale Daten gelöscht"
            "stop_failed" -> "Datenaufnahme gesperrt · Abmeldung prüfen"
            else -> "Noch nicht aktiviert"
        }
    }

    val capabilityMessage = when (heartRateCapability) {
        HeartRateCapability.Checking -> "Sensorprüfung läuft…"
        HeartRateCapability.Supported -> when {
            sleepStateSupported && stepsSupported -> "Herz-, Schritt- und Schlafstatus verfügbar"
            sleepStateSupported -> "Herz- und Schlafstatus verfügbar"
            stepsSupported -> "Herz- und Schrittkanal verfügbar"
            else -> "Herzsensor verfügbar · ohne Zusatzkanäle"
        }
        HeartRateCapability.Unsupported -> "Passiver Herzsensor nicht verfügbar"
        is HeartRateCapability.Failed -> "Health Services nicht erreichbar"
    }

    val actionLabel = when {
        heartRateCapability != HeartRateCapability.Supported -> "Sensor nicht verfügbar"
        registrationBusy -> "Aktivierung läuft…"
        missingPermission != null -> "Berechtigung erteilen"
        backgroundActive -> "Messung beenden"
        else -> "Lokale Messung starten"
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 10.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        BedOutlineMark()
        Spacer(Modifier.height(5.dp))
        Text("REJUVENATION BED", color = Amber)
        Text("Schlafanalyse")
        Spacer(Modifier.height(5.dp))
        Text(capabilityMessage, color = Muted)
        Spacer(Modifier.height(7.dp))
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(Color(0xFF17130E))
                .padding(8.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text("SCHLAFPHASE", color = Muted)
            Text("UNKNOWN", color = Amber)
            Text("Noch keine validierte Schlafphase", color = Muted)
            Text(
                "Lokal: ${localSnapshot.heartRateSampleCount} Puls · ${localSnapshot.stepIntervalCount} Aktivitätsintervalle",
                color = Muted
            )
            Text("Auswertbare 30-min-Fenster: $featureWindowCount", color = Muted)
            Text(latestWindow?.let { formatFeatureWindow(it) } ?: "Warte auf vollständige Messfenster", color = Muted)
            if (sleepStateSupported) {
                Text(
                    platformSleepLabel?.let { "Wear OS: $it" } ?: "Wear OS: Status noch nicht gemeldet",
                    color = Muted
                )
            }
        }
        Spacer(Modifier.height(6.dp))
        Button(
            enabled = heartRateCapability == HeartRateCapability.Supported && !registrationBusy,
            onClick = {
                if (backgroundActive) {
                    registrationBusy = true
                    PassiveHeartRateRegistration.stop(context) { result ->
                        registrationBusy = false
                        sensorMessage = if (result.isSuccess) {
                            "Messung beendet · lokale Daten gelöscht"
                        } else {
                            "Messung konnte nicht beendet werden"
                        }
                        permissionVersion += 1
                    }
                } else if (missingPermission != null) {
                    permissionLauncher.launch(missingPermission)
                } else {
                    registrationBusy = true
                    sensorMessage = "Health Services wird aktiviert…"
                    PassiveHeartRateRegistration.start(
                        context,
                        includeSteps = stepsSupported,
                        includeUserActivityInfo = sleepStateSupported
                    ) { result ->
                        registrationBusy = false
                        sensorMessage = if (result.isSuccess) {
                            "Hintergrundmessung registriert"
                        } else {
                            "Registrierung fehlgeschlagen"
                        }
                        permissionVersion += 1
                    }
                }
            }
        ) {
            Text(actionLabel)
        }
        Spacer(Modifier.height(4.dp))
        Text(
            text = sensorMessage,
            color = Muted
        )
        Text(
            text = "Daten bleiben lokal auf der Uhr.",
            color = Muted
        )
        Spacer(Modifier.height(8.dp))
        Text("Wischen zum Thermostat →", color = Amber)
    }
}

@Composable
private fun ThermostatPage(
    targetTemperature: Float,
    onTemperatureChange: (Float) -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 12.dp, vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        BedOutlineMark()
        Spacer(Modifier.height(4.dp))
        Text("BETTTHERMOSTAT", color = Amber)
        Spacer(Modifier.height(4.dp))
        TemperatureDial(
            temperature = targetTemperature,
            onTemperatureChange = onTemperatureChange
        )
        Spacer(Modifier.height(2.dp))
        Text("VORSCHAU · NICHT VERBUNDEN", color = Muted)
        Text("← Wischen zur Schlafanalyse", color = Amber)
    }
}

/**
 * Round touch dial with a 270-degree amber arc and a bottom gap.
 * The touch mapping snaps to 0.5 °C steps and never sends a real command.
 */
@Composable
private fun TemperatureDial(
    temperature: Float,
    onTemperatureChange: (Float) -> Unit
) {
    val minimum = MIN_BED_TEMPERATURE
    val maximum = MAX_BED_TEMPERATURE

    Box(
        modifier = Modifier
            .size(132.dp)
            .pointerInput(minimum, maximum, onTemperatureChange) {
                detectTapGestures { point ->
                    TemperatureDialScale.fromPosition(
                        x = point.x,
                        y = point.y,
                        width = size.width.toFloat(),
                        height = size.height.toFloat(),
                        minimum = minimum,
                        maximum = maximum
                    )?.let(onTemperatureChange)
                }
            }
            .pointerInput(minimum, maximum, onTemperatureChange) {
                detectDragGestures { change, _ ->
                    change.consume()
                    TemperatureDialScale.fromPosition(
                        x = change.position.x,
                        y = change.position.y,
                        width = size.width.toFloat(),
                        height = size.height.toFloat(),
                        minimum = minimum,
                        maximum = maximum
                    )?.let(onTemperatureChange)
                }
            },
        contentAlignment = Alignment.Center
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val strokeWidth = 7.dp.toPx()
            val arcSize = Size(size.width - strokeWidth, size.height - strokeWidth)
            val topLeft = Offset(strokeWidth / 2f, strokeWidth / 2f)

            drawArc(
                color = Color(0xFF3A3024),
                startAngle = 135f,
                sweepAngle = 270f,
                useCenter = false,
                topLeft = topLeft,
                size = arcSize,
                style = Stroke(width = strokeWidth, cap = StrokeCap.Round)
            )

            val progress = ((temperature - minimum) / (maximum - minimum)).coerceIn(0f, 1f)
            val sweep = progress * 270f
            drawArc(
                color = Amber,
                startAngle = 135f,
                sweepAngle = sweep,
                useCenter = false,
                topLeft = topLeft,
                size = arcSize,
                style = Stroke(width = strokeWidth, cap = StrokeCap.Round)
            )

            val angle = Math.toRadians((135f + sweep).toDouble())
            val radius = min(size.width, size.height) / 2f - strokeWidth / 2f
            val knobCenter = Offset(
                x = size.width / 2f + cos(angle).toFloat() * radius,
                y = size.height / 2f + sin(angle).toFloat() * radius
            )
            drawCircle(color = Midnight, radius = 7.dp.toPx(), center = knobCenter)
            drawCircle(color = Amber, radius = 5.dp.toPx(), center = knobCenter)
        }

        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = String.format(Locale.GERMANY, "%.1f°", temperature),
                color = Amber
            )
            Text("ZIELTEMP.", color = Muted)
            Text("ZIEHEN", color = Muted)
        }
    }
}


private data class LocalSleepSnapshot(
    val heartRateSampleCount: Int,
    val stepIntervalCount: Int,
    val windows: List<SleepFeatureWindow>,
    val collectionStatus: String,
    val platformSleepState: PlatformSleepStateEvent?
)

private fun formatFeatureWindow(window: SleepFeatureWindow): String {
    val mean = window.heartRateMeanBpm?.let { String.format(Locale.GERMANY, "Ø %.0f bpm", it) } ?: "Puls —"
    return "$mean · ${window.stepsInWindow} Schritte"
}

@Composable
private fun rememberLocalSleepSnapshot(context: Context): LocalSleepSnapshot {
    val preferences = remember(context) {
        context.getSharedPreferences("rejuvenation_bed_watch_health", Context.MODE_PRIVATE)
    }
    var revision by remember { mutableIntStateOf(0) }

    DisposableEffect(preferences) {
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
            if (
                key == "heart_rate_samples" ||
                key == "step_intervals" ||
                key == "user_activity_states" ||
                key == "heart_rate_collection_status" ||
                key == "heart_rate_collection_enabled"
            ) {
                revision += 1
            }
        }
        preferences.registerOnSharedPreferenceChangeListener(listener)
        onDispose {
            preferences.unregisterOnSharedPreferenceChangeListener(listener)
        }
    }

    return remember(revision) {
        val heartRate = HeartRateSampleStore.heartRateSamples(context)
        val steps = HeartRateSampleStore.stepIntervals(context)
        LocalSleepSnapshot(
            heartRateSampleCount = heartRate.size,
            stepIntervalCount = steps.size,
            windows = SleepFeatureExtractor.extract(
                heartRateSamples = heartRate,
                stepIntervals = steps,
                nowEpochMillis = System.currentTimeMillis()
            ),
            collectionStatus = HeartRateSampleStore.status(context),
            platformSleepState = HeartRateSampleStore.latestPlatformSleepState(context)
        )
    }
}
