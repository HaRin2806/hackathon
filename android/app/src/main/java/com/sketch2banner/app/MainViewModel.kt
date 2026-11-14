package com.sketch2banner.app

import android.app.Application
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.util.UUID

enum class Role { SKETCH, PRODUCT }

data class HistoryEvent(val id: String, val event: String, val year: Int, val summary: String, val verified: Boolean) {
    fun toJson(): String = JSONObject().put("id", id).put("event", event).put("year", year)
        .put("summary", summary).put("verified", verified).toString()

    companion object {
        fun from(o: JSONObject) = HistoryEvent(o.getString("id"), o.getString("event"), o.getInt("year"),
            o.optString("summary"), o.optBoolean("verified"))
    }
}

data class VariantInfo(val id: String, val style: String)

data class JobResult(
    val jobId: String,
    val token: String,
    val variants: List<VariantInfo>,
    val layoutReading: String,
    val suggestedLayout: Boolean,
    val isFixture: Boolean,
    val modelId: String,
    val createdAt: String,
    val headlineFromAi: Boolean,
    val headlineUsed: String,
    val totalMs: Long,
    val aiMs: Long,
    val isOld: Boolean,
)

/**
 * All state survives a force-stop (spec §10):
 *  - picked images are copied into filesDir,
 *  - the brief + client_request_id are saved BEFORE the POST,
 *  - job_id + job_token are saved right after the 202,
 *  - on next launch we resume polling the same job (or re-POST with the same request id -> same job).
 */
class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("s2b", Context.MODE_PRIVATE)
    private val sketchFile = File(app.filesDir, "input/sketch.jpg")
    private val productFile = File(app.filesDir, "input/product.jpg")

    var baseUrl by mutableStateOf(prefs.getString("baseUrl", BuildConfig.DEFAULT_BASE_URL)!!)
        private set
    private val api = Api { baseUrl }

    var sketchPreview by mutableStateOf<Bitmap?>(null); private set
    var productPreview by mutableStateOf<Bitmap?>(null); private set

    var productName by mutableStateOf(prefs.getString("productName", "")!!); private set
    var headline by mutableStateOf(prefs.getString("headline", "")!!); private set
    var price by mutableStateOf(prefs.getString("price", "")!!); private set
    var cta by mutableStateOf(prefs.getString("cta", "")!!); private set
    var selectedEvent by mutableStateOf(prefs.getString("event", null)?.let {
        runCatching { HistoryEvent.from(JSONObject(it)) }.getOrNull()
    }); private set

    var health by mutableStateOf("Đang kiểm tra server…"); private set
    var healthOk by mutableStateOf<Boolean?>(null); private set
    var serverIsFixture by mutableStateOf(false); private set

    var busy by mutableStateOf(false); private set
    var stage by mutableStateOf<String?>(null); private set
    var currentJobId by mutableStateOf<String?>(null); private set
    var startedAt by mutableStateOf(0L); private set
    var error by mutableStateOf<String?>(null); private set
    var canRetry by mutableStateOf(false); private set

    var result by mutableStateOf<JobResult?>(null); private set
    val thumbs = mutableStateMapOf<String, Bitmap>()
    var toast by mutableStateOf<String?>(null)

    val events = mutableStateListOf<HistoryEvent>()
    var eventsMessage by mutableStateOf<String?>(null); private set

    private var pollJob: Job? = null
    private var foreground = false

    init {
        viewModelScope.launch(Dispatchers.IO) {
            val s = Images.preview(sketchFile)
            val p = Images.preview(productFile)
            withContext(Dispatchers.Main) { sketchPreview = s; productPreview = p }
        }
        checkHealth()
        // Restore an in-flight generation after process death.
        val jobId = prefs.getString("pendingJobId", null)
        val token = prefs.getString("pendingToken", null)
        if (jobId != null && token != null) {
            busy = true; currentJobId = jobId; stage = "QUEUED"
            startedAt = prefs.getLong("pendingStarted", System.currentTimeMillis())
        } else if (prefs.getString("pendingRequestId", null) != null) {
            error = "Lượt tạo trước bị gián đoạn trước khi server xác nhận. Bấm “Thử lại” để gửi lại đúng yêu cầu đó (không tạo trùng)."
            canRetry = true
        } else {
            prefs.getString("lastJobId", null)?.let { id ->
                prefs.getString("lastToken", null)?.let { tok -> loadResult(id, tok, isOld = true) }
            }
        }
    }

    // ---------- lifecycle: poll only in foreground (spec §08) ----------
    fun onForeground() {
        foreground = true
        val id = prefs.getString("pendingJobId", null)
        val tok = prefs.getString("pendingToken", null)
        if (id != null && tok != null && pollJob?.isActive != true) startPolling(id, tok)
    }

    fun onBackground() {
        foreground = false
        pollJob?.cancel()
    }

    // ---------- inputs ----------
    fun setImage(role: Role, uri: Uri) {
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val dest = if (role == Role.SKETCH) sketchFile else productFile
                Images.importToFile(getApplication(), uri, dest)
                val bmp = Images.preview(dest)
                withContext(Dispatchers.Main) {
                    if (role == Role.SKETCH) sketchPreview = bmp else productPreview = bmp
                    invalidatePendingRequest()
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) { toast = "Không đọc được ảnh, hãy chọn ảnh khác." }
            }
        }
    }

    fun updateField(name: String, value: String) {
        when (name) {
            "productName" -> productName = value.take(60)
            "headline" -> headline = value.take(80)
            "price" -> price = value.take(40)
            "cta" -> cta = value.take(40)
        }
        prefs.edit().putString(name, value).apply()
        invalidatePendingRequest()
    }

    fun selectEvent(e: HistoryEvent?) {
        selectedEvent = e
        prefs.edit().putString("event", e?.toJson()).apply()
        invalidatePendingRequest()
    }

    /** Inputs changed and no job was created yet -> the old request id no longer describes this payload. */
    private fun invalidatePendingRequest() {
        if (!busy && prefs.getString("pendingJobId", null) == null && prefs.getString("pendingRequestId", null) != null) {
            prefs.edit().remove("pendingRequestId").apply()
            canRetry = false
        }
    }

    fun updateBaseUrl(url: String) {
        baseUrl = url.trim().trimEnd('/')
        prefs.edit().putString("baseUrl", baseUrl).apply()
        checkHealth()
    }

    val canGenerate: Boolean
        get() = !busy && sketchPreview != null && productPreview != null && productName.isNotBlank() && cta.isNotBlank()

    fun checkHealth() {
        healthOk = null; health = "Đang kiểm tra server…"
        viewModelScope.launch(Dispatchers.IO) {
            val (ok, text, fixture) = try {
                val h = api.health()
                val fixture = h.optString("provider") == "mock"
                val keyOk = h.optBoolean("ai_key_configured")
                Triple(!fixture && keyOk, when {
                    fixture -> "FIXTURE (mock) — không phải AI"
                    !keyOk -> "${h.optString("model_id")} · thiếu API key"
                    else -> h.optString("model_id")
                }, fixture)
            } catch (e: Exception) {
                Triple(false, "Không kết nối được server", false)
            }
            withContext(Dispatchers.Main) { healthOk = ok; health = text; serverIsFixture = fixture }
        }
    }

    // ---------- history ----------
    fun searchEvents(q: String, today: Boolean = false) {
        val md = if (today) java.text.SimpleDateFormat("MM-dd", java.util.Locale.US).format(java.util.Date()) else ""
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val items = api.events(q, md).getJSONArray("items")
                val list = (0 until items.length()).map { HistoryEvent.from(items.getJSONObject(it)) }
                withContext(Dispatchers.Main) {
                    events.clear(); events.addAll(list)
                    eventsMessage = if (list.isEmpty()) "Không có sự kiện phù hợp." else null
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) { events.clear(); eventsMessage = "Không tải được danh sách sự kiện." }
            }
        }
    }

    // ---------- generate ----------
    private fun briefJson(): String = JSONObject()
        .put("product_name", productName.trim())
        .put("headline", headline.trim())
        .put("price", price.trim())
        .put("cta", cta.trim())
        .put("history_event_id", selectedEvent?.id ?: JSONObject.NULL)
        .toString()

    fun generate() {
        if (!canGenerate) return
        val requestId = UUID.randomUUID().toString()
        val now = System.currentTimeMillis()
        prefs.edit()  // saved BEFORE the POST (spec §10 step 2)
            .putString("pendingRequestId", requestId)
            .putString("pendingBrief", briefJson())
            .putLong("pendingStarted", now)
            .commit()
        submit(requestId, now)
    }

    fun retry() {
        val requestId = prefs.getString("pendingRequestId", null) ?: return generate()
        submit(requestId, System.currentTimeMillis())
    }

    private fun submit(requestId: String, started: Long) {
        busy = true; error = null; canRetry = false; result = null; thumbs.clear()
        stage = "QUEUED"; startedAt = started; currentJobId = null
        val brief = prefs.getString("pendingBrief", null) ?: briefJson()
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val r = api.create(sketchFile, productFile, brief, requestId)
                val id = r.getString("job_id")
                val tok = r.getString("job_token")
                prefs.edit().putString("pendingJobId", id).putString("pendingToken", tok).commit()
                withContext(Dispatchers.Main) {
                    currentJobId = id
                    if (foreground) startPolling(id, tok)
                }
            } catch (e: ApiException) {
                withContext(Dispatchers.Main) {
                    // Client-side input errors will not succeed on retry: drop the request id.
                    if (e.code.startsWith("invalid") || e.code.endsWith("too_large") || e.code == "request_id_conflict") {
                        prefs.edit().remove("pendingRequestId").apply()
                        fail("${e.message} (mã: ${e.code})", retry = false)
                    } else fail("${e.message} (mã: ${e.code})", retry = true)
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    fail("Không gửi được yêu cầu. Kiểm tra Wi-Fi và địa chỉ server ($baseUrl).", retry = true)
                }
            }
        }
    }

    private fun startPolling(id: String, token: String) {
        pollJob?.cancel()
        pollJob = viewModelScope.launch(Dispatchers.IO) {
            var misses = 0
            while (isActive) {
                try {
                    val j = api.job(id, token)
                    misses = 0
                    val st = j.optString("status")
                    withContext(Dispatchers.Main) { stage = j.optString("stage") }
                    when (st) {
                        "SUCCEEDED" -> {
                            prefs.edit().remove("pendingRequestId").remove("pendingJobId").remove("pendingToken")
                                .putString("lastJobId", id).putString("lastToken", token).commit()
                            withContext(Dispatchers.Main) { busy = false; stage = "SUCCEEDED" }
                            applyResult(j, token, isOld = false)
                            return@launch
                        }
                        "FAILED", "INTERRUPTED" -> {
                            prefs.edit().remove("pendingRequestId").remove("pendingJobId").remove("pendingToken").commit()
                            withContext(Dispatchers.Main) {
                                fail("${j.optString("error_message", "Tạo thất bại.")} (mã: ${j.optString("error_code")})", retry = false)
                            }
                            return@launch
                        }
                    }
                } catch (e: ApiException) {
                    if (e.code == "job_not_found" || e.code == "bad_token") {
                        prefs.edit().remove("pendingJobId").remove("pendingToken").remove("pendingRequestId").commit()
                        withContext(Dispatchers.Main) { fail("Server không còn job này. Hãy tạo lượt mới.", retry = false) }
                        return@launch
                    }
                    misses++
                } catch (e: Exception) {
                    misses++ // transient network problem: keep the job, keep polling
                }
                if (misses == 10) withContext(Dispatchers.Main) {
                    error = "Mất kết nối tới server, đang thử lại… (job $id vẫn được giữ)"
                }
                delay(1000)
            }
        }
    }

    private fun fail(msg: String, retry: Boolean) {
        busy = false; stage = null; error = msg; canRetry = retry
    }

    private fun loadResult(id: String, token: String, isOld: Boolean) {
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val j = api.job(id, token)
                if (j.optString("status") == "SUCCEEDED") applyResult(j, token, isOld)
            } catch (_: Exception) { }
        }
    }

    private suspend fun applyResult(j: JSONObject, token: String, isOld: Boolean) {
        val vs = j.optJSONArray("variants")
        val variants = (0 until (vs?.length() ?: 0)).map {
            val o = vs!!.getJSONObject(it); VariantInfo(o.getString("id"), o.optString("style"))
        }
        val m = j.optJSONObject("metrics")
        val res = JobResult(
            jobId = j.getString("job_id"), token = token, variants = variants,
            layoutReading = j.optString("layout_reading"),
            suggestedLayout = j.optString("layout_source") == "suggested",
            isFixture = j.optBoolean("is_fixture"),
            modelId = j.optString("model_id"), createdAt = j.optString("created_at"),
            headlineFromAi = j.optString("headline_source") == "ai_suggestion",
            headlineUsed = j.optString("headline_used"),
            totalMs = m?.optLong("total_ms") ?: 0L, aiMs = m?.optLong("ai_ms") ?: 0L, isOld = isOld,
        )
        withContext(Dispatchers.Main) { result = res; error = null; thumbs.clear() }
        for (v in variants) {  // thumbnails first; the full PNG only when viewing/saving (spec §11)
            try {
                val b = api.bytes("/v1/generations/${res.jobId}/variants/${v.id}/thumbnail", token)
                BitmapFactory.decodeByteArray(b, 0, b.size)?.let { bmp -> withContext(Dispatchers.Main) { thumbs[v.id] = bmp } }
            } catch (_: Exception) { }
        }
    }

    // ---------- full image / export ----------
    var fullImage by mutableStateOf<Bitmap?>(null); private set
    var viewing by mutableStateOf<String?>(null); private set
    private var fullPng: ByteArray? = null

    fun openVariant(id: String) {
        val r = result ?: return
        viewing = id; fullImage = null; fullPng = null
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val png = api.bytes("/v1/generations/${r.jobId}/variants/$id.png", r.token)
                val bmp = BitmapFactory.decodeByteArray(png, 0, png.size)
                withContext(Dispatchers.Main) { fullPng = png; fullImage = bmp }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) { toast = "Không tải được ảnh lớn."; viewing = null }
            }
        }
    }

    fun closeViewer() { viewing = null; fullImage = null; fullPng = null }

    private fun fileName(): String = "sketch2banner_${result?.jobId}_${viewing}.png"

    fun saveCurrent() {
        val png = fullPng ?: return
        viewModelScope.launch(Dispatchers.IO) {
            val uri = runCatching { Images.saveToGallery(getApplication(), png, fileName()) }.getOrNull()
            withContext(Dispatchers.Main) {
                toast = if (uri != null) "Đã lưu vào Ảnh › Pictures/Sketch2Banner (1080×1080)" else "Không lưu được — hãy dùng Chia sẻ."
            }
        }
    }

    fun shareCurrent(ctx: Context) {
        val png = fullPng ?: return
        runCatching { Images.share(ctx, png, fileName()) }.onFailure { toast = "Không chia sẻ được." }
    }
}
