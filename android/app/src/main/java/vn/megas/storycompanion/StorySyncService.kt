package vn.megas.storycompanion

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.os.SystemClock

class StorySyncService : Service() {
    companion object {
        private const val CHANNEL_ID = "megas_story_sync"
        private const val NOTIFICATION_ID = 4101
    }

    @Volatile private var running = false
    private var workerThread: Thread? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
        val openApp = Intent(this, MainActivity::class.java)
        val pending = PendingIntent.getActivity(
            this, 0, openApp,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            android.app.Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("MEGAS Story Companion")
                .setContentText("Đang chờ Story từ Railway")
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentIntent(pending)
                .setOngoing(true)
                .build()
        } else {
            @Suppress("DEPRECATION")
            android.app.Notification.Builder(this)
                .setContentTitle("MEGAS Story Companion")
                .setContentText("Đang chờ Story từ Railway")
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentIntent(pending)
                .setOngoing(true)
                .build()
        }
        startForeground(NOTIFICATION_ID, notification)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (workerThread?.isAlive != true) {
            running = true
            workerThread = Thread { loop() }.also { it.start() }
        }
        return START_STICKY
    }

    private fun loop() {
        while (running) {
            try {
                if (Prefs.currentJob(this).isBlank()) {
                    pollOnce()
                }
            } catch (e: Exception) {
                Prefs.status(this, "Lỗi sync: ${e.message ?: e.javaClass.simpleName}")
            }
            SystemClock.sleep(15_000)
        }
    }

    private fun pollOnce() {
        if (Prefs.token(this).isBlank()) {
            Prefs.status(this, "Chưa có Android API token")
            return
        }
        val client = ApiClient(this)
        val job = client.nextJob()
        if (job == null) {
            Prefs.status(this, "Đang chờ job…")
            return
        }

        val jobId = job.getString("job_id")
        client.claim(jobId)
        try {
            Prefs.status(this, "Đang tải media: $jobId")
            val downloaded = client.download(jobId)
            val mediaUri = MediaStoreHelper.save(this, downloaded)

            Prefs.store(this).edit()
                .putString("current_job_id", jobId)
                .putString("current_link_url", job.optString("link_url", ""))
                .putString("current_link_text", job.optString("link_text", ""))
                .putString("current_media_uri", mediaUri.toString())
                .putBoolean("publish_allowed", job.optBoolean("publish_allowed", false))
                .putString("automation_stage", "OPEN_META")
                .apply()

            val launch = packageManager.getLaunchIntentForPackage("com.facebook.pages.app")
            if (launch == null) {
                client.result(jobId, "RELEASE", "META_BUSINESS_SUITE_NOT_INSTALLED")
                Prefs.clearJob(this)
                Prefs.status(this, "Chưa cài Meta Business Suite")
                return
            }
            launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            startActivity(launch)
            Prefs.status(this, "Đã mở Meta Business Suite cho job $jobId")
        } catch (e: Exception) {
            try {
                client.result(jobId, "RELEASE", e.message ?: e.javaClass.simpleName)
            } catch (_: Exception) {
            }
            Prefs.clearJob(this)
            throw e
        }
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "MEGAS Story Sync",
                NotificationManager.IMPORTANCE_LOW
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    override fun onDestroy() {
        running = false
        workerThread = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
