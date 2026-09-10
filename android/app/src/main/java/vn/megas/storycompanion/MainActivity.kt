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
    private lateinit var tokenInput: EditText
    private lateinit var statusText: TextView
    private val handler = Handler(Looper.getMainLooper())
    @Volatile private var pilotStarting = false

    private val refresh = object : Runnable {
        override fun run() {
            val prefs = Prefs.store(this@MainActivity)
            val status = prefs.getString("status", "Chưa chạy") ?: "Chưa chạy"
            val stage = prefs.getString("automation_stage", "") ?: ""
            val job = prefs.getString("current_job_id", "") ?: ""
            statusText.text = buildString {
                append("Backend cố định: ").append(Prefs.DEFAULT_BACKEND)
                append("\nChế độ APK: PILOT SAFE — không có code Publish")
                append("\nTrạng thái: ").append(status)
                if (job.isNotBlank()) append("\nJob đang giữ: ").append(job)
                if (stage.isNotBlank()) append("\nStage: ").append(stage)
            }
            handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
        requestRuntimePermissions()
        if (Prefs.currentJob(this).isNotBlank()) {
            Prefs.status(this, "Phát hiện job dang dở. Hãy Release job server trước khi chạy pilot mới.")
        }
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
            text = "MEGAS Story Companion — Pilot Safe"
            textSize = 24f
            setTypeface(typeface, Typeface.BOLD)
        })
        root.addView(TextView(this).apply {
            text = "Facebook/Meta chỉ đăng nhập trực tiếp trên điện thoại. Bản pilot này chỉ được phép đi tới thư viện Story để map UI; không có code chọn ảnh, Link Sticker hay Publish."
            textSize = 15f
            setPadding(0, dp(8), 0, dp(18))
        })

        root.addView(label("Railway backend (đã khóa trong app)"))
        root.addView(TextView(this).apply {
            text = Prefs.DEFAULT_BACKEND
            setTextIsSelectable(true)
        })

        root.addView(label("Android API token"))
        tokenInput = EditText(this).apply {
            hint = if (Prefs.token(this@MainActivity).isBlank()) "Dán token từ Railway Variables" else "Token đã lưu an toàn — dán mới để thay"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            isSingleLine = true
        }
        root.addView(tokenInput, fullWidth())

        root.addView(button("Lưu token") { saveToken() })
        root.addView(button("Test kết nối + khóa an toàn") {
            if (tokenInput.text.toString().isNotBlank()) saveToken(showToast = false)
            testConnection()
        })
        root.addView(button("Mở cài đặt Accessibility") {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        })
        root.addView(button("Mở Meta Business Suite thủ công") { openMeta() })
        root.addView(button("Chạy 1 Pilot Dry-Run") {
            if (tokenInput.text.toString().isNotBlank()) saveToken(showToast = false)
            runPilotOnce()
        })
        root.addView(button("Release job server + reset local") { releaseCurrentJob() })
        root.addView(button("Copy UI diagnostic") { copyDiagnostic() })

        statusText = TextView(this).apply {
            textSize = 15f
            setPadding(0, dp(20), 0, dp(8))
            setTextIsSelectable(true)
        }
        root.addView(statusText, fullWidth())

        root.addView(TextView(this).apply {
            text = "Fail-safe: nếu server không báo đồng thời ANDROID + dry_run=true + pilot_safe_mode=true, app sẽ từ chối chạy. Nếu UI có 0 hoặc nhiều hơn 1 nút phù hợp, Accessibility cũng dừng và không click."
            textSize = 13f
        })

        setContentView(scroll)
    }

    private fun label(value: String) = TextView(this).apply {
        text = value
        textSize = 14f
        setTypeface(typeface, Typeface.BOLD)
        setPadding(0, dp(8), 0, 0)
    }

    private fun button(value: String, action: () -> Unit) = Button(this).apply {
        text = value
        setOnClickListener { action() }
    }

    private fun fullWidth() = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT,
        LinearLayout.LayoutParams.WRAP_CONTENT,
    )

    private fun saveToken(showToast: Boolean = true) {
        val token = tokenInput.text.toString().trim()
        if (token.isBlank()) {
            if (Prefs.token(this).isBlank()) toast("Chưa có token để lưu")
            return
        }
        if (token.length < 32) {
            toast("Token không hợp lệ: phải dài ít nhất 32 ký tự")
            return
        }
        Prefs.setToken(this, token)
        tokenInput.setText("")
        tokenInput.hint = "Token đã lưu an toàn — dán mới để thay"
        if (showToast) toast("Đã lưu token bằng Android Keystore")
    }

    private fun validatePilotServer(body: org.json.JSONObject) {
        if (!body.optBoolean("ok", false)) error("SERVER_NOT_OK")
        if (body.optString("transport", "") != "ANDROID") error("SERVER_TRANSPORT_NOT_ANDROID")
        if (!body.optBoolean("dry_run", false)) error("SERVER_DRY_RUN_IS_OFF")
        if (!body.optBoolean("pilot_safe_mode", false)) error("SERVER_PILOT_SAFE_MODE_IS_OFF")
    }

    private fun testConnection() {
        if (Prefs.token(this).length < 32) {
            toast("Hãy lưu Android API token trước")
            return
        }
        Prefs.status(this, "Đang test Railway và safety locks…")
        Thread {
            try {
                val body = ApiClient(this).ping()
                validatePilotServer(body)
                Prefs.status(this, "Railway OK — ANDROID + dry_run + pilot_safe_mode đều bật")
                runOnUiThread { toast("Safety check PASS") }
            } catch (e: Exception) {
                Prefs.status(this, "Safety check FAIL: ${e.message}")
                runOnUiThread { toast("Không an toàn để chạy pilot") }
            }
        }.start()
    }

    private fun runPilotOnce() {
        if (pilotStarting) {
            toast("Pilot đang khởi động, không bấm lặp")
            return
        }
        if (Prefs.token(this).length < 32) {
            toast("Hãy lưu Android API token trước")
            return
        }
        if (Prefs.currentJob(this).isNotBlank()) {
            toast("Đang có job dang dở. Hãy Release trước.")
            return
        }
        if (packageManager.getLaunchIntentForPackage("com.facebook.pages.app") == null) {
            toast("Chưa cài Meta Business Suite")
            return
        }

        pilotStarting = true
        Prefs.status(this, "Pilot: đang kiểm tra server…")
        Thread {
            var claimedJobId = ""
            var claimToken = ""
            try {
                val client = ApiClient(this)
                validatePilotServer(client.ping())
                val next = client.nextJob() ?: error("KHÔNG_CÓ_JOB_VALIDATED_ĐẾN_HẠN")
                claimedJobId = next.getString("job_id")
                if (claimedJobId.isBlank()) error("JOB_ID_EMPTY")

                val claimed = client.claim(claimedJobId)
                claimToken = claimed.getString("claim_token")
                if (claimToken.length < 20) error("CLAIM_TOKEN_INVALID")
                if (claimed.optBoolean("publish_allowed", true)) error("PILOT_REFUSES_PUBLISH_ALLOWED_TRUE")
                if (!claimed.optBoolean("dry_run", false)) error("PILOT_REFUSES_DRY_RUN_FALSE")
                if (!claimed.optBoolean("pilot_safe_mode", false)) error("PILOT_REFUSES_SAFE_MODE_FALSE")

                // Persist claim before any download so a process death is recoverable.
                Prefs.setClaimedJob(
                    this,
                    claimedJobId,
                    claimToken,
                    claimed.optString("link_url", ""),
                    claimed.optString("link_text", ""),
                    "CLAIMED",
                )

                Prefs.status(this, "Pilot: đang tải media $claimedJobId")
                val downloaded = client.download(claimedJobId, claimToken)
                val mediaUri = MediaStoreHelper.save(this, downloaded)
                Prefs.setMediaUri(this, mediaUri.toString())
                Prefs.store(this).edit().putString("automation_stage", "OPEN_META").commit()

                Prefs.status(this, "Pilot: mở Meta Business Suite — chỉ map tới thư viện")
                runOnUiThread {
                    openMeta()
                    toast("Pilot đã bắt đầu — không chạm điện thoại cho tới khi app dừng")
                }
            } catch (e: Exception) {
                val message = e.message ?: e.javaClass.simpleName
                if (claimedJobId.isNotBlank() && claimToken.isNotBlank()) {
                    try {
                        ApiClient(this).result(
                            claimedJobId,
                            claimToken,
                            "RELEASE",
                            error = "PILOT_START_FAILED:$message",
                            note = "Released by visible Activity",
                        )
                        Prefs.clearJob(this)
                    } catch (releaseError: Exception) {
                        Prefs.status(this, "Pilot fail + release fail. Giữ job để recovery: ${releaseError.message}")
                        runOnUiThread { toast("Job được giữ để recovery — không reset tay") }
                        return@Thread
                    }
                }
                Prefs.status(this, "Pilot không chạy: $message")
                runOnUiThread { toast("Pilot dừng an toàn") }
            } finally {
                pilotStarting = false
            }
        }.start()
    }

    private fun releaseCurrentJob() {
        val jobId = Prefs.currentJob(this)
        val claim = Prefs.claimToken(this)
        if (jobId.isBlank()) {
            toast("Không có job local để release")
            return
        }
        if (claim.isBlank()) {
            Prefs.status(this, "Có job local nhưng thiếu claim token. Chờ lease server hết hạn rồi thử pilot lại.")
            toast("Không force-clear để tránh lệch state")
            return
        }
        Prefs.status(this, "Đang release job $jobId…")
        Thread {
            try {
                ApiClient(this).result(
                    jobId,
                    claim,
                    "RELEASE",
                    error = "USER_REQUESTED_RECOVERY",
                    note = "Manual recovery from companion app",
                )
                Prefs.clearJob(this)
                Prefs.status(this, "Đã release server và reset local")
                runOnUiThread { toast("Recovery hoàn tất") }
            } catch (e: Exception) {
                Prefs.status(this, "Release chưa thành công, local job được giữ: ${e.message}")
                runOnUiThread { toast("Chưa release được — không xóa local") }
            }
        }.start()
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
            toast("Chưa có diagnostic từ Meta Business Suite")
            return
        }
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("MEGAS UI diagnostic", dump))
        toast("Đã copy UI diagnostic")
    }

    private fun requestRuntimePermissions() {
        if (Build.VERSION.SDK_INT <= 28 &&
            checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE), 1001)
        }
    }

    private fun toast(value: String) = Toast.makeText(this, value, Toast.LENGTH_SHORT).show()
    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    override fun onDestroy() {
        handler.removeCallbacks(refresh)
        super.onDestroy()
    }
}
