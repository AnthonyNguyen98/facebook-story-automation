package vn.megas.storycompanion

import android.content.Context
import android.content.SharedPreferences

object Prefs {
    const val DEFAULT_BACKEND = "https://story-worker-production.up.railway.app"

    fun store(context: Context): SharedPreferences =
        context.getSharedPreferences("megas_story_companion", Context.MODE_PRIVATE)

    fun backend(context: Context): String =
        store(context).getString("backend_url", DEFAULT_BACKEND)?.trim()?.trimEnd('/') ?: DEFAULT_BACKEND

    fun token(context: Context): String =
        store(context).getString("api_token", "") ?: ""

    fun status(context: Context, value: String) {
        store(context).edit().putString("status", value).apply()
    }

    fun currentJob(context: Context): String =
        store(context).getString("current_job_id", "") ?: ""

    fun clearJob(context: Context) {
        store(context).edit()
            .remove("current_job_id")
            .remove("current_link_url")
            .remove("current_link_text")
            .remove("current_media_uri")
            .remove("publish_allowed")
            .remove("automation_stage")
            .apply()
    }
}
