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

    private val baseUrl: String get() = Prefs.backend(context)
    private val token: String get() = Prefs.token(context)

    private fun pathJobId(jobId: String): String =
        URLEncoder.encode(jobId, StandardCharsets.UTF_8.toString()).replace("+", "%20")

    private fun open(path: String, method: String = "GET"): HttpURLConnection {
        val conn = URL(baseUrl + path).openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = 15_000
        conn.readTimeout = 90_000
        conn.setRequestProperty("Authorization", "Bearer $token")
        conn.setRequestProperty("Accept", "application/json")
        conn.instanceFollowRedirects = true
        return conn
    }

    private fun readJson(conn: HttpURLConnection): JSONObject {
        val code = conn.responseCode
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream
        val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
        if (code !in 200..299) {
            throw IOException("HTTP $code ${text.take(500)}")
        }
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
        conn.outputStream.use { it.write("{}".toByteArray()) }
        return try { readJson(conn) } finally { conn.disconnect() }
    }

    fun download(jobId: String): DownloadedMedia {
        val conn = open("/api/android/jobs/${pathJobId(jobId)}/media")
        val code = conn.responseCode
        if (code !in 200..299) {
            val error = conn.errorStream?.bufferedReader()?.use { it.readText() } ?: ""
            conn.disconnect()
            throw IOException("MEDIA HTTP $code ${error.take(500)}")
        }
        val mime = conn.contentType?.substringBefore(';')?.trim().orEmpty().ifBlank { "application/octet-stream" }
        val disposition = conn.getHeaderField("Content-Disposition").orEmpty()
        val fileName = Regex("filename=\\\"?([^\\\";]+)").find(disposition)?.groupValues?.getOrNull(1)
            ?: if (mime.startsWith("video/")) "story.mp4" else "story.jpg"
        val suffix = fileName.substringAfterLast('.', if (mime.startsWith("video/")) "mp4" else "jpg")
        val out = File(context.cacheDir, "story_${System.currentTimeMillis()}.$suffix")
        try {
            conn.inputStream.use { input ->
                FileOutputStream(out).use { output -> input.copyTo(output) }
            }
        } finally {
            conn.disconnect()
        }
        return DownloadedMedia(out, mime, fileName)
    }

    fun result(jobId: String, state: String, error: String = "", note: String = ""): JSONObject {
        val conn = open("/api/android/jobs/${pathJobId(jobId)}/result", "POST")
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/json")
        val payload = JSONObject()
            .put("state", state)
            .put("error", error)
            .put("note", note)
            .toString()
        conn.outputStream.use { it.write(payload.toByteArray()) }
        return try { readJson(conn) } finally { conn.disconnect() }
    }
}
