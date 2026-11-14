package net.schanz.rejuvenationbed.watch

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp

private val Amber = Color(0xFFE5A23B)

@Composable
fun BedOutlineMark(modifier: Modifier = Modifier) {
    Canvas(modifier = modifier.size(48.dp)) {
        val strokeWidth = 2.2.dp.toPx()
        val outline = Stroke(width = strokeWidth, cap = StrokeCap.Round)
        val w = size.width
        val h = size.height

        drawLine(Amber, Offset(w * 0.10f, h * 0.48f), Offset(w * 0.10f, h * 0.83f), strokeWidth, StrokeCap.Round)
        drawLine(Amber, Offset(w * 0.10f, h * 0.66f), Offset(w * 0.90f, h * 0.66f), strokeWidth, StrokeCap.Round)
        drawLine(Amber, Offset(w * 0.90f, h * 0.48f), Offset(w * 0.90f, h * 0.83f), strokeWidth, StrokeCap.Round)
        drawLine(Amber, Offset(w * 0.10f, h * 0.83f), Offset(w * 0.10f, h * 0.91f), strokeWidth, StrokeCap.Round)
        drawLine(Amber, Offset(w * 0.90f, h * 0.83f), Offset(w * 0.90f, h * 0.91f), strokeWidth, StrokeCap.Round)
        drawRoundRect(
            color = Amber,
            topLeft = Offset(w * 0.18f, h * 0.31f),
            size = Size(w * 0.28f, h * 0.35f),
            cornerRadius = CornerRadius(5.dp.toPx()),
            style = outline
        )
        drawLine(Amber, Offset(w * 0.46f, h * 0.56f), Offset(w * 0.82f, h * 0.56f), strokeWidth, StrokeCap.Round)
    }
}
