package vn.megas.storycompanion

import android.content.Context
import android.content.SharedPreferences
import java.util.UUID

object Prefs {
    const val DEFAULT_BACKEND = "https://story-worker-production.up.railway.app"
    const val PILOT_SAFE_MODE = true
    private const val API_TOKEN_KEY = "api_token"
    private const val CLAIM_TOKEN_KEY = "claim_token"

    fun store(context: Context): SharedPreferences =
        context.getSharedPreferences("megas_story_companion", Context.MODE_PRIVATE)

    fun backend(@Suppress("UNUSED_PARAMETER") context: Context): String = DEFAULT_BACKEND

    fun token(context: Context): String = SecretStore.get(context, API_TOKEN_KEY)

    fun setToken(context: Context, value: String) = SecretStore.put(context, API_TOKEN_KEY, value.trim())

    fun claimToken(context: Context): String = SecretStore.get(context, CLAIM_TOKEN_KEY)

    fun setClaimToken(context: Context, value: String) = SecretStore.put(context, CLAIM_TOKEN_KEY, value)

    fun deviceId(context: Context): String {
        val prefs = store(context)
        val existing = prefs.getString("device_id", "").orEmpty()
        if (existing.length >= 8) return existing
        val generated = "android-${UUID.randomUUID()}"
        prefs.edit().putString("device_id", generated).commit()
        return generated
    }

    fun status(context: Context, value: String) {
        store(context).edit().putString("status", value.take(1200)).apply()
    }

    fun currentJob(context: Context): String =
        store(context).getString("current_job_id", "") ?: ""

    fun setClaimedJob(
        context: Context,
        jobId: String,
        claimToken: String,
        linkUrl: String,
        linkText: String,
        stage: String,
    ) {
        setClaimToken(context, claimToken)
        store(context).edit()
            .putString("current_job_id", jobId)
            .putString("current_link_url", linkUrl)
            .putString("current_link_text", linkText)
            .putBoolean("publish_allowed", false) // Pilot hard-lock: never trust remote flag.
            .putString("automation_stage", stage)
            .commit()
    }

    fun setMediaUri(context: Context, uri: String) {
        store(context).edit().putString("current_media_uri", uri).commit()
    }

    fun clearJob(context: Context) {
        SecretStore.remove(context, CLAIM_TOKEN_KEY)
        store(context).edit()
            .remove("current_job_id")
            .remove("current_link_url")
            .remove("current_link_text")
            .remove("current_media_uri")
            .remove("publish_allowed")
            .remove("automation_stage")
            .remove("pilot_running")
            .apply()
    }
}
