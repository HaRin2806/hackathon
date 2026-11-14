package com.sketch2banner.app

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.delay

private val Brand = Color(0xFF4F5BD5)
private val BrandTint = Color(0xFFEEF0FF)
private val Surface2 = Color(0xFFF3F4FF)
private val Muted = Color(0xFF6B7090)
private val Safe = Color(0xFF059669)
private val SafeTint = Color(0xFFE7F7F0)
private val Caution = Color(0xFFB45309)
private val CautionTint = Color(0xFFFFF6E5)
private val Danger = Color(0xFFB91C1C)
private val DangerTint = Color(0xFFFDECEC)

private val STYLE_LABEL = mapOf("A" to "Bám phác thảo", "B" to "Tối giản", "C" to "Nhấn ưu đãi")
private val STAGES = listOf("QUEUED" to "Tải lên", "ANALYZING" to "AI đọc phác thảo",
    "VALIDATING" to "Kiểm tra", "RENDERING" to "Dựng 3 ảnh")

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = Brand, secondary = Brand)) { App(vm) }
        }
    }

    override fun onStart() { super.onStart(); vm.onForeground() }
    override fun onStop() { vm.onBackground(); super.onStop() }
}

@Composable
fun App(vm: MainViewModel) {
    val ctx = LocalContext.current
    LaunchedEffect(vm.toast) {
        vm.toast?.let { Toast.makeText(ctx, it, Toast.LENGTH_LONG).show(); vm.toast = null }
    }
    var showServer by remember { mutableStateOf(false) }

    Column(
        Modifier.fillMaxSize().background(Color(0xFFF4F2FF)).statusBarsPadding().navigationBarsPadding()
            .imePadding().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Header(vm) { showServer = true }
        if (vm.serverIsFixture) Banner("Server đang ở chế độ FIXTURE (mock): kết quả KHÔNG phải AI. Cấu hình AI_API_KEY trước khi demo.", DangerTint, Danger)
        InputsCard(vm)
        BriefCard(vm)
        HistoryCard(vm)
        GenerateCard(vm)
        vm.result?.let { ResultCard(vm, it) }
        Spacer(Modifier.height(24.dp))
    }

    if (showServer) ServerDialog(vm) { showServer = false }
    if (vm.viewing != null) Viewer(vm)
}

@Composable
private fun Header(vm: MainViewModel, onServer: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Box(Modifier.size(44.dp).clip(RoundedCornerShape(14.dp)).background(Brand), contentAlignment = Alignment.Center) {
            Text("S2B", color = Color.White, fontWeight = FontWeight.ExtraBold, fontSize = 14.sp)
        }
        Column(Modifier.weight(1f)) {
            Text("Sketch2Banner", fontWeight = FontWeight.Bold, fontSize = 20.sp)
            Text("Phác thảo tay + ảnh thật → 3 banner", color = Muted, fontSize = 13.sp)
        }
        TextButton(onClick = onServer) { Text("Server") }
    }
    val (bg, fg) = when (vm.healthOk) { true -> SafeTint to Safe; false -> DangerTint to Danger; null -> Surface2 to Muted }
    Chip(vm.health, bg, fg, Modifier.clickable { vm.checkHealth() })
}

@Composable
private fun SectionCard(title: String, step: String? = null, content: @Composable () -> Unit) {
    Card(shape = RoundedCornerShape(24.dp), colors = CardDefaults.cardColors(containerColor = Color.White),
        elevation = CardDefaults.cardElevation(2.dp)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (step != null) Box(Modifier.size(26.dp).clip(CircleShape).background(BrandTint), contentAlignment = Alignment.Center) {
                    Text(step, color = Brand, fontWeight = FontWeight.ExtraBold, fontSize = 14.sp)
                }
                Text(title, fontWeight = FontWeight.Bold, fontSize = 17.sp)
            }
            content()
        }
    }
}

@Composable
private fun InputsCard(vm: MainViewModel) {
    val pickSketch = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { it?.let { u -> vm.setImage(Role.SKETCH, u) } }
    val pickProduct = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { it?.let { u -> vm.setImage(Role.PRODUCT, u) } }
    val req = PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
    SectionCard("Hai ảnh đầu vào", "1") {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            ImageSlot(Modifier.weight(1f), "Phác thảo", "Vẽ ô, ghi nhãn TIÊU ĐỀ · SP · GIÁ · CTA", vm.sketchPreview) { pickSketch.launch(req) }
            ImageSlot(Modifier.weight(1f), "Sản phẩm", "Ảnh thật, nền đơn giản, đủ sáng", vm.productPreview) { pickProduct.launch(req) }
        }
    }
}

@Composable
private fun ImageSlot(modifier: Modifier, label: String, hint: String, bmp: android.graphics.Bitmap?, onPick: () -> Unit) {
    Box(
        modifier.aspectRatio(1f).clip(RoundedCornerShape(20.dp)).background(Surface2)
            .border(2.dp, if (bmp != null) Color(0xFF8C99F8) else Color(0xFFE3E5F5), RoundedCornerShape(20.dp))
            .clickable(onClick = onPick),
        contentAlignment = Alignment.Center,
    ) {
        if (bmp != null) {
            Image(bmp.asImageBitmap(), label, Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
        } else {
            Column(Modifier.padding(10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text("+ Chọn ảnh", fontWeight = FontWeight.Bold)
                Text(hint, color = Muted, fontSize = 11.sp, lineHeight = 15.sp)
            }
        }
        Box(Modifier.align(Alignment.TopStart).padding(8.dp).clip(RoundedCornerShape(50)).background(Brand)
            .padding(horizontal = 9.dp, vertical = 3.dp)) {
            Text(if (bmp != null) "$label · đổi" else label, color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun BriefCard(vm: MainViewModel) {
    SectionCard("Nội dung bán hàng", "2") {
        Text("Giá, ưu đãi và CTA do bạn xác nhận; AI không tự đoán hay sửa.", color = Muted, fontSize = 13.sp)
        Field("Tên sản phẩm *", vm.productName, "Trà sữa trân châu đường đen") { vm.updateField("productName", it) }
        Field("Tiêu đề (trống = AI gợi ý)", vm.headline, "Mát lạnh ngày hè") { vm.updateField("headline", it) }
        Field("Giá / ưu đãi", vm.price, "39.000đ") { vm.updateField("price", it) }
        Field("Lời kêu gọi (CTA) *", vm.cta, "Đặt ngay hôm nay") { vm.updateField("cta", it) }
    }
}

@Composable
private fun Field(label: String, value: String, placeholder: String, onChange: (String) -> Unit) {
    OutlinedTextField(value, onChange, Modifier.fillMaxWidth(), label = { Text(label) },
        placeholder = { Text(placeholder, color = Muted) }, singleLine = true, shape = RoundedCornerShape(14.dp))
}

@Composable
private fun HistoryCard(vm: MainViewModel) {
    var open by remember { mutableStateOf(false) }
    var q by remember { mutableStateOf("") }
    SectionCard("Gắn dịp lịch sử (tuỳ chọn)") {
        vm.selectedEvent?.let { e ->
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(BrandTint).padding(10.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("Đã gắn: ${e.year} · ${e.event}", Modifier.weight(1f), fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                TextButton(onClick = { vm.selectEvent(null) }) { Text("Bỏ") }
            }
        }
        if (!open) {
            OutlinedButton(onClick = { open = true; vm.searchEvents("") }, shape = RoundedCornerShape(14.dp)) {
                Text("“Ngày này năm xưa” — chọn sự kiện")
            }
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(q, { q = it; vm.searchEvents(it) }, Modifier.weight(1f), singleLine = true,
                    placeholder = { Text("Điện Biên Phủ, 1010…", color = Muted) }, shape = RoundedCornerShape(14.dp))
                OutlinedButton(onClick = { q = ""; vm.searchEvents("", today = true) }) { Text("Hôm nay") }
            }
            vm.eventsMessage?.let { Text(it, color = Muted, fontSize = 13.sp) }
            vm.events.take(8).forEach { e ->
                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Surface2)
                    .clickable { vm.selectEvent(e); open = false }.padding(10.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("${e.year}  ", color = Brand, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                        Text(e.event, Modifier.weight(1f), fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                        Chip(if (e.verified) "đã kiểm" else "chưa kiểm chứng",
                            if (e.verified) SafeTint else CautionTint, if (e.verified) Safe else Caution)
                    }
                    if (e.summary.isNotBlank()) Text(e.summary, color = Muted, fontSize = 12.sp, lineHeight = 16.sp)
                }
            }
            Text("Nguồn: sự kiện chọn lọc + dataset Vietnam-History-1M-Vi (MIT).", color = Muted, fontSize = 11.sp)
        }
    }
}

@Composable
private fun GenerateCard(vm: MainViewModel) {
    SectionCard("Tạo bằng AI", "3") {
        Button(onClick = { vm.generate() }, enabled = vm.canGenerate, modifier = Modifier.fillMaxWidth().height(54.dp),
            shape = RoundedCornerShape(16.dp), colors = ButtonDefaults.buttonColors(containerColor = Brand)) {
            if (vm.busy) {
                CircularProgressIndicator(Modifier.size(20.dp), color = Color.White, strokeWidth = 2.dp)
                Spacer(Modifier.size(10.dp)); Text("Đang tạo…", fontSize = 16.sp)
            } else Text("Tạo 3 phương án", fontSize = 16.sp, fontWeight = FontWeight.Bold)
        }
        Text("Cần kết nối tới server. Chọn đủ 2 ảnh, tên sản phẩm và CTA.", color = Muted, fontSize = 12.sp)

        if (vm.busy || vm.stage == "SUCCEEDED") {
            val idx = STAGES.indexOfFirst { it.first == vm.stage }.let { if (vm.stage == "SUCCEEDED") STAGES.size else it }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                STAGES.forEachIndexed { i, (_, label) ->
                    val (bg, fg) = when { i < idx -> SafeTint to Safe; i == idx -> BrandTint to Brand; else -> Surface2 to Muted }
                    Box(Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).background(bg).padding(vertical = 9.dp, horizontal = 2.dp),
                        contentAlignment = Alignment.Center) {
                        Text(label, color = fg, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, lineHeight = 13.sp)
                    }
                }
            }
            if (vm.busy) {
                var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
                LaunchedEffect(vm.busy) { while (true) { now = System.currentTimeMillis(); delay(500) } }
                Text("${(now - vm.startedAt) / 1000}s · job ${vm.currentJobId ?: "—"}", color = Muted, fontSize = 12.sp)
            }
        }
        vm.error?.let {
            Banner(it, DangerTint, Danger)
            if (vm.canRetry) OutlinedButton(onClick = { vm.retry() }, enabled = !vm.busy) { Text("Thử lại (cùng yêu cầu)") }
        }
    }
}

@Composable
private fun ResultCard(vm: MainViewModel, r: JobResult) {
    SectionCard("Kết quả") {
        when {
            r.isFixture -> Chip("FIXTURE — không phải AI", DangerTint, Danger)
            r.isOld -> Chip("Kết quả cũ (mở lại từ lịch sử)", CautionTint, Caution)
            else -> Chip("Lượt AI mới", SafeTint, Safe)
        }
        Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Surface2).padding(12.dp)) {
            Text("AI đọc phác thảo:", color = Brand, fontWeight = FontWeight.Bold, fontSize = 13.sp)
            Text(r.layoutReading.ifBlank { "—" }, fontSize = 13.sp)
            if (r.headlineFromAi) Text("Tiêu đề do AI gợi ý: “${r.headlineUsed}”", color = Muted, fontSize = 12.sp)
        }
        if (r.suggestedLayout) Banner("AI chưa đọc rõ phác thảo — đây là BỐ CỤC GỢI Ý, không phải bố cục bạn vẽ. Hãy chụp rõ hơn và ghi nhãn từng ô.", CautionTint, Caution)
        r.variants.forEach { v ->
            Card(shape = RoundedCornerShape(18.dp), colors = CardDefaults.cardColors(containerColor = Surface2),
                modifier = Modifier.fillMaxWidth().clickable { vm.openVariant(v.id) }) {
                Box(Modifier.fillMaxWidth().aspectRatio(1f), contentAlignment = Alignment.Center) {
                    val t = vm.thumbs[v.id]
                    if (t != null) Image(t.asImageBitmap(), "Phương án ${v.id}", Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
                    else CircularProgressIndicator()
                }
                Row(Modifier.padding(12.dp)) {
                    Text("${v.id} — ${STYLE_LABEL[v.id] ?: v.style}", Modifier.weight(1f), fontWeight = FontWeight.Bold)
                    Text("Xem / Lưu", color = Brand)
                }
            }
        }
        Text("job ${r.jobId} · model ${r.modelId} · ${r.createdAt}" +
            if (r.totalMs > 0) " · server ${"%.1f".format(r.totalMs / 1000.0)}s (AI ${"%.1f".format(r.aiMs / 1000.0)}s)" else "",
            color = Muted, fontSize = 11.sp)
    }
}

@Composable
private fun Viewer(vm: MainViewModel) {
    val ctx = LocalContext.current
    Dialog(onDismissRequest = { vm.closeViewer() }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(Modifier.fillMaxWidth().padding(12.dp).clip(RoundedCornerShape(22.dp)).background(Color.White)) {
            Box(Modifier.fillMaxWidth().aspectRatio(1f), contentAlignment = Alignment.Center) {
                val img = vm.fullImage
                if (img != null) Image(img.asImageBitmap(), "Banner", Modifier.fillMaxSize()) else CircularProgressIndicator()
            }
            Text("Phương án ${vm.viewing} — ${STYLE_LABEL[vm.viewing] ?: ""} · PNG 1080×1080",
                Modifier.padding(horizontal = 14.dp, vertical = 8.dp), fontSize = 13.sp, color = Muted)
            Row(Modifier.fillMaxWidth().padding(12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { vm.saveCurrent() }, enabled = vm.fullImage != null, modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = Brand)) { Text("Lưu PNG") }
                OutlinedButton(onClick = { vm.shareCurrent(ctx) }, enabled = vm.fullImage != null, modifier = Modifier.weight(1f)) { Text("Chia sẻ") }
                TextButton(onClick = { vm.closeViewer() }) { Text("Đóng") }
            }
        }
    }
}

@Composable
private fun ServerDialog(vm: MainViewModel, onClose: () -> Unit) {
    var url by remember { mutableStateOf(vm.baseUrl) }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("Địa chỉ server") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(url, { url = it }, singleLine = true, modifier = Modifier.fillMaxWidth())
                Text("LAN: http://<IP laptop>:8000 (cùng Wi-Fi)\nHoặc URL HTTPS của tunnel.", color = Muted, fontSize = 12.sp)
            }
        },
        confirmButton = { TextButton(onClick = { vm.updateBaseUrl(url); onClose() }) { Text("Lưu & kiểm tra") } },
        dismissButton = { TextButton(onClick = onClose) { Text("Huỷ") } },
    )
}

@Composable
private fun Chip(text: String, bg: Color, fg: Color, modifier: Modifier = Modifier) {
    Box(modifier.clip(RoundedCornerShape(50)).background(bg).padding(horizontal = 10.dp, vertical = 4.dp)) {
        Text(text, color = fg, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun Banner(text: String, bg: Color, fg: Color) {
    Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(bg).border(BorderStroke(0.dp, bg), RoundedCornerShape(14.dp)).padding(12.dp)) {
        Text(text, color = fg, fontSize = 13.sp, lineHeight = 18.sp)
    }
}
