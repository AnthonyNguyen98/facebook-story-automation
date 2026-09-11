package vn.megas.storycompanion

import java.util.Locale

object UiMatcher {
    fun normalize(value: CharSequence?): String = value
        ?.toString()
        ?.trim()
        ?.lowercase(Locale.ROOT)
        ?.replace(Regex("\\s+"), " ")
        .orEmpty()

    fun exact(value: CharSequence?, terms: Collection<String>): Boolean {
        val normalized = normalize(value)
        if (normalized.isBlank()) return false
        return terms.any { normalized == normalize(it) }
    }

    fun exactEither(text: CharSequence?, description: CharSequence?, terms: Collection<String>): Boolean =
        exact(text, terms) || exact(description, terms)
}
