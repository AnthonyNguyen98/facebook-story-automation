package vn.megas.storycompanion

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

object SecretStore {
    private const val ALIAS = "megas_story_companion_v1"
    private const val PREFS = "megas_story_secrets"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build()
        )
        return generator.generateKey()
    }

    fun put(context: Context, name: String, value: String) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (value.isBlank()) {
            prefs.edit().remove(name).apply()
            return
        }
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        val payload = ByteArray(1 + cipher.iv.size + encrypted.size)
        payload[0] = cipher.iv.size.toByte()
        System.arraycopy(cipher.iv, 0, payload, 1, cipher.iv.size)
        System.arraycopy(encrypted, 0, payload, 1 + cipher.iv.size, encrypted.size)
        prefs.edit().putString(name, Base64.encodeToString(payload, Base64.NO_WRAP)).apply()
    }

    fun get(context: Context, name: String): String {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val encoded = prefs.getString(name, null) ?: return ""
        return try {
            val payload = Base64.decode(encoded, Base64.NO_WRAP)
            if (payload.size < 14) return ""
            val ivSize = payload[0].toInt() and 0xFF
            if (ivSize !in 12..32 || payload.size <= 1 + ivSize) return ""
            val iv = payload.copyOfRange(1, 1 + ivSize)
            val data = payload.copyOfRange(1 + ivSize, payload.size)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
            String(cipher.doFinal(data), Charsets.UTF_8)
        } catch (_: Exception) {
            ""
        }
    }

    fun remove(context: Context, name: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(name).apply()
    }
}
