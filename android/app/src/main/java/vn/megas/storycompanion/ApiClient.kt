package vn.megas.storycompanion

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

class ApiClient(private val context: Context) {
    data class DownloadedMedia(val file: File, val mimeType: String, val fileName: String)

    companion object {
        const val MAX_MEDIA_BYTES: Long = 262_144_000L
        const val USER_AGENT = "MEGAS-Story-Companion/0.2.1-pilot"
    }

    private val baseUrl: String get() = Prefs.DEFAULT_BACKEND
    private val token: String get() = Prefs.token(context)
    private val deviceId: String get() = Prefs.deviceId(context)

    private fun pathJobId(jobId: String): String =
        URLEncoder.encode(jobId, StandardCharsets.UTF_8.toString()).replace("+", "%20")

    private fun open(path: String, method: String = "GET", claimToken: String = ""): HttpURLConnection {
        if (!baseUrl.startsWith("https://")) throw IOException("BACKEND_MUST_USE_HTTPS")
        if (token.length < 32) throw IOException("ANDROID_API_TOKEN_TOO_SHORT")
        val conn = URL(baseUrl + path).openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = 15_000
        conn.readTimeout = 120_000
        conn.setRequestProperty("Authorization", "Bearer $token")
        conn.setRequestProperty("X-Device-Id", deviceId)
        if (claimToken.isNotBlank()) conn.setRequestProperty("X-Claim-Token", claimToken)
        conn.setRequestProperty("Accept", "application/json")
        conn.setRequestProperty("User-Agent", USER_AGENT)
        conn.instanceFollowRedirects = false
        return conn
    }

    private fun readJson(conn: HttpURLConnection): JSONObject {
        val code = conn.responseCode
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream
        val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
        if (code !in 200..299) throw IOException("HTTP $code ${text.take(500)}")
        return if (text.isBlank()) JSONObject() else JSONObject(text)
    }

    fun ping(): JSONObject {
        val conn = open("/api/android/ping")
        return try { readJson(conn) } finally { conn.disconnect() }
    }

    fun nextJob(): JSONObject? {
        val conn = open("/api/android/jobs/next")
        return try {
            val body = readJson(conn)
            if (body.isNull("job")) null else body.optJSONObject("job")
        } finally {
            conn.disconnect()
        }
    }

    fun claim(jobId: String): JSONObject {
        val conn = open("/api/android/jobs/${pathJobId(jobId)}/claim", "POST")
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/json")
        conn.outputStream.use { it.write("{}".toByteArray(Charsets.UTF_8)) }
        return try {
            val body = readJson(conn)
            body.optJSONObject("job") ?: throw IOException("CLAIM_RESPONSE_MISSING_JOB")
        } finally {
            conn.disconnect()
        }
    }

    fun download(jobId: String, claimToken: String): DownloadedMedia {
        val conn = open("/api/android/jobs/${pathJobId(jobId)}/media", claimToken = claimToken)
        val code = conn.responseCode
        if (code !in 200..299) {
            val error = conn.errorStream?.bufferedReader()?.use { it.readText() } ?: ""
            conn.disconnect()
            throw IOException("MEDIA HTTP $code ${error.take(500)}")
        }
        val mime = conn.contentType?.substringBefore(';')?.trim().orEmpty()
        if (!(mime.startsWith("image/") || mime.startsWith("video/"))) {
            conn.disconnect()
            throw IOException("UNSUPPORTED_MEDIA_TYPE:$mime")
        }
        val length = conn.contentLengthLong
        if (length > MAX_MEDIA_BYTES) {
            conn.disconnect()
            throw IOException("MEDIA_TOO_LARGE:$length")
        }

        val disposition = conn.getHeaderField("Content-Disposition").orEmpty()
        val rawName = Regex("filename=\\\"?([^\\\";]+)").find(disposition)?.groupValues?.getOrNull(1)
            ?: if (mime.startsWith("video/")) "story.mp4" else "story.jpg"
        val fileName = rawName.replace(Regex("[^A-Za-z0-9._-]"), "_").take(160).ifBlank {
            if (mime.startsWith("video/")) "story.mp4" else "story.jpg"
        }
        val rawSuffix = fileName.substringAfterLast('.', "").lowercase()
        val suffix = when (rawSuffix) {
            "mp4", "mov", "m4v", "webm", "jpg", "jpeg", "png", "webp" -> rawSuffix
            else -> if (mime.startsWith("video/")) "mp4" else "jpg"
        }
        val out = File(context.cacheDir, "story_${System.currentTimeMillis()}.$suffix")
        try {
            var total = 0L
            conn.inputStream.use { input ->
                FileOutputStream(out).use { output ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        total += read
                        if (total > MAX_MEDIA_BYTES) throw IOException("MEDIA_STREAM_EXCEEDED_LIMIT")
                        output.write(buffer, 0, read)
                    }
                }
            }
            if (total <= 0L) throw IOException("MEDIA_DOWNLOAD_EMPTY")
            return DownloadedMedia(out, mime, fileName)
        } catch (e: Exception) {
            out.delete()
            throw e
        } finally {
            conn.disconnect()
        }
    }

    fun result(
        jobId: String,
        claimToken: String,
        state: String,
        error: String = "",
        note: String = "",
    ): JSONObject {
        val conn = open(
            "/api/android/jobs/${pathJobId(jobId)}/result",
            "POST",
            claimToken,
        )
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/json")
        val payload = JSONObject()
            .put("state", state)
            .put("error", error.take(1500))
            .put("note", note.take(1000))
            .toString()
        conn.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }
        return try { readJson(conn) } finally { conn.disconnect() }
    }
}
