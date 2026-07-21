package com.twoazone.skylight.uploader

import android.content.Context

object Prefs {
    private const val NAME = "skylight_prefs"
    private const val KEY_PIN = "pin"
    private const val KEY_STYLE = "style"

    fun getPin(ctx: Context): String =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE).getString(KEY_PIN, "") ?: ""

    fun setPin(ctx: Context, pin: String) {
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)
            .edit().putString(KEY_PIN, pin).apply()
    }

    fun getStyle(ctx: Context): String =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE).getString(KEY_STYLE, "pill") ?: "pill"

    fun setStyle(ctx: Context, style: String) {
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)
            .edit().putString(KEY_STYLE, style).apply()
    }
}
