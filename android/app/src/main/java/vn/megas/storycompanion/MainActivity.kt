package vn.megas.storycompanion

import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {
    private lateinit var backendInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var statusText: TextView
    private val handler = Handler(Looper.getMainLooper())

    private val refresh = object : Runnable {
        override fun run() {
            val prefs = Prefs.store(this@MainActivity)
            val status = prefs.getString("status", "Chưa chạy") ?: "Chưa chạy"
            val stage = prefs.getString("automation_stage", "") ?: ""
            val job = prefs.getString("current_job_id", "") ?: ""
            statusText.text = buildString {
                append("Trạng thái: ").append(status)
                if (job.isNotBlank()) append("\nJob: ").append(job)
                if (stage.isNotBlank()) append("\nStage: ").append(stage)
            }
            handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
        requestRuntimePermissions()
        handler.post(refresh)
    }

    private fun buildUi() {
        val scroll = ScrollView(this)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(24), dp(20), dp(32))
        }
        scroll.addView(root, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))

        root.addView(TextView(this).apply {
            text = "MEGAS Story Companion"
            textSize = 24f
            setTypeface(typeface, Typeface.BOLD)
        })
        root.addView(TextView(this).apply {
            text = "Facebook/Meta chỉ đăng nhập trực tiếp trên điện thoại này. App không nhận, đọc hoặc gửi mật khẩu/cookie Facebook lên Railway."
            textSize = 15f
            setPadding(0, dp(8), 0, dp(18))
        })

        root.addView(label("Railway backend"))
        backendInput = EditText(this).apply {
            setText(Prefs.backend(this@MainActivity))
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            isSingleLine = true
        }
        root.addView(backendInput, fullWidth())

        root.addView(label("Android API token"))
        tokenInput = EditText(this).apply {
            setText(Prefs.token(this@MainActivity))
            hint = "Dán token từ Railway Variables"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            isSingleLine = true
        }
        root.addView(tokenInput, fullWidth())

        root.addView(button("Lưu cấu hình") { saveSettings() })
        root.addView(button("Test kết nối Railway") {
            saveSettings()
            testConnection()
        })
        root.addView(button("Mở cài đặt Accessibility") {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        })
        root.addView(button("Mở Meta Business Suite") { openMeta() })
        root.addView(button("Bật Story Sync") {
            saveSettings()
            startSync()
        })
        root.addView(button("Tắt Story Sync") {
            stopService(Intent(this, StorySyncService::class.java))
            Prefs.status(this, "Story Sync đã tắt")
        })
        root.addView(button("Copy UI diagnostic") { copyDiagnostic() })
        root.addView(button("Reset job đang giữ trên máy") {
            Prefs.clearJob(this)
            Prefs.status(this, "Đã reset local job")
        })

        statusText = TextView(this).apply {
            textSize = 15f
            setPadding(0, dp(20), 0, dp(8))
            setTextIsSelectable(true)
        }
        root.addView(statusText, fullWidth())

        root.addView(TextView(this).apply {
            text = "Bản 0.1 dùng fail-safe: không tìm đúng control thì dừng. Lần test đầu sẽ map chính xác gallery/Link Sticker trên model Android này trước khi cho phép auto-publish."
            textSize = 13f
        })

        setContentView(scroll)
    }

    private fun label(textValue: String) = TextView(this).apply {
        text = textValue
        textSize = 14f
        setTypeface(typeface, Typeface.BOLD)
        setPadding(0, dp(8), 0, 0)
    }

    private fun button(textValue: String, action: () -> Unit) = Button(this).apply {
        text = textValue
        setOnClickListener { action() }
    }

    private fun fullWidth() = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT,
        LinearLayout.LayoutParams.WRAP_CONTENT
    )

    private fun saveSettings() {
        val backend = backendInput.text.toString().trim().trimEnd('/').ifBlank { Prefs.DEFAULT_BACKEND }
        val token = tokenInput.text.toString().trim()
        Prefs.store(this).edit()
            .putString("backend_url", backend)
            .putString("api_token", token)
            .apply()
        toast("Đã lưu")
    }

    private fun testConnection() {
        Prefs.status(this, "Đang test Railway…")
        Thread {
            try {
                val body = ApiClient(this).ping()
                val dry = body.optBoolean("dry_run", true)
                val transport = body.optString("transport", "")
                Prefs.status(this, "Railway OK — transport=$transport, dry_run=$dry")
                runOnUiThread { toast("Kết nối Railway thành công") }
            } catch (e: Exception) {
                Prefs.status(this, "Railway FAIL: ${e.message}")
                runOnUiThread { toast("Kết nối thất bại") }
            }
        }.start()
    }

    private fun startSync() {
        if (Prefs.token(this).isBlank()) {
            toast("Hãy nhập Android API token trước")
            return
        }
        val intent = Intent(this, StorySyncService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent) else startService(intent)
        Prefs.status(this, "Story Sync đang khởi động")
    }

    private fun openMeta() {
        val launch = packageManager.getLaunchIntentForPackage("com.facebook.pages.app")
        if (launch == null) {
            toast("Chưa cài Meta Business Suite")
            return
        }
        startActivity(launch)
    }

    private fun copyDiagnostic() {
        val dump = Prefs.store(this).getString("last_ui_dump", "") ?: ""
        if (dump.isBlank()) {
            toast("Chưa có diagnostic. Hãy mở Meta sau khi bật Accessibility.")
            return
        }
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("MEGAS UI diagnostic", dump))
        toast("Đã copy UI diagnostic")
    }

    private fun requestRuntimePermissions() {
        val needed = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (Build.VERSION.SDK_INT <= 28 && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        }
        if (needed.isNotEmpty()) requestPermissions(needed.toTypedArray(), 1001)
    }

    private fun toast(textValue: String) = Toast.makeText(this, textValue, Toast.LENGTH_SHORT).show()
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    override fun onDestroy() {
        handler.removeCallbacks(refresh)
        super.onDestroy()
    }
}
