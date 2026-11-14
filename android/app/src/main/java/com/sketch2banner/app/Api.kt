package com.sketch2banner.app

import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Error with the backend's error_code (spec §08) so the UI can show a clear, specific message. */
class ApiException(val code: String, message: String) : IOException(message)

/** Thin client for the Sketch2Banner API. The OpenAI/Gemini key never lives in the APK. */
class Api(private val baseUrl: () -> String) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    private fun url(path: String) = baseUrl().trim().trimEnd('/') + path

    private fun execJson(req: Request): JSONObject {
        client.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            val json = try { JSONObject(text) } catch (e: Exception) { JSONObject() }
            if (!resp.isSuccessful) {
                val d = json.optJSONObject("detail")
                val code = d?.optString("error_code").orEmpty().ifBlank { "http_${resp.code}" }
                val msg = d?.optString("message").orEmpty().ifBlank { "Lỗi server (${resp.code})." }
                throw ApiException(code, msg)
            }
            return json
        }
    }

    fun health(): JSONObject = execJson(Request.Builder().url(url("/health")).build())

    fun create(sketch: File, product: File, briefJson: String, requestId: String): JSONObject {
        val jpeg = "image/jpeg".toMediaType()
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("sketch", "sketch.jpg", sketch.asRequestBody(jpeg))
            .addFormDataPart("product", "product.jpg", product.asRequestBody(jpeg))
            .addFormDataPart("brief_json", briefJson)
            .addFormDataPart("client_request_id", requestId)
            .build()
        return execJson(Request.Builder().url(url("/v1/generations")).post(body).build())
    }

    fun job(id: String, token: String): JSONObject =
        execJson(Request.Builder().url(url("/v1/generations/$id")).header("X-Job-Token", token).build())

    fun bytes(path: String, token: String): ByteArray {
        val req = Request.Builder().url(url(path)).header("X-Job-Token", token).build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) throw ApiException("http_${resp.code}", "Không tải được ảnh (${resp.code}).")
            return resp.body?.bytes() ?: ByteArray(0)
        }
    }

    fun events(q: String, monthDay: String): JSONObject {
        val u = url("/v1/history/events").toHttpUrl().newBuilder()
            .addQueryParameter("q", q)
            .addQueryParameter("month_day", monthDay)
            .addQueryParameter("limit", "12")
            .build()
        return execJson(Request.Builder().url(u).build())
    }
}
