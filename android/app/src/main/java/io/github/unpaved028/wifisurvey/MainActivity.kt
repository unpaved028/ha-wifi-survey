package io.github.unpaved028.wifisurvey

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.view.WindowManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.FrameLayout

/**
 * Hülle um die Web-Oberfläche von wifi-survey. Die Oberfläche kommt vom Server; die App liefert
 * ihr über die Brücke „WifiSurveyApp“ die WLAN-Werte des Handys (verbundener Zugangspunkt, Scan).
 */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private val prefs by lazy { getSharedPreferences("wifi-survey", MODE_PRIVATE) }
    private var dialogOpen = false

    private val scanReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val updated = intent.getBooleanExtra(WifiManager.EXTRA_RESULTS_UPDATED, false)
            notifyPage("wifiscan", "{updated: $updated}")
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.webChromeClient = WebChromeClient()
        web.webViewClient = object : WebViewClient() {
            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) askServer("Der Server antwortet nicht (${error.description}).")
            }
        }
        web.addJavascriptInterface(WifiBridge(this), "WifiSurveyApp")
        setContentView(FrameLayout(this).apply { addView(web) })

        val filter = IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION)
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(scanReceiver, filter, Context.RECEIVER_EXPORTED)
        } else {
            registerReceiver(scanReceiver, filter)
        }

        val server = prefs.getString("server", null) ?: BuildConfig.DEFAULT_SERVER
        if (server.isBlank()) askServer(null) else open(server)
    }

    override fun onDestroy() {
        unregisterReceiver(scanReceiver)
        web.destroy()
        super.onDestroy()
    }

    @Deprecated("Zurück-Taste: erst in der Web-Oberfläche zurück")
    override fun onBackPressed() {
        @Suppress("DEPRECATION")
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        notifyPage("wifipermission", "{}")
    }

    override fun onResume() {
        super.onResume()
        notifyPage("wifipermission", "{}")   // zurück aus den Einstellungen (z. B. Standort „Immer zulassen“)
    }

    /** Standort im Hintergrund: ab Android 11 öffnet Android dafür die Einstellungen („Immer zulassen“). */
    fun askBackgroundLocation() {
        if (Build.VERSION.SDK_INT >= 29) requestPermissions(arrayOf(Manifest.permission.ACCESS_BACKGROUND_LOCATION), 2)
    }

    private fun open(server: String) {
        web.loadUrl(server.trim().trimEnd('/') + "/#/messen")
    }

    /** Ereignis an die Web-Oberfläche: window.addEventListener(name, (e) => e.detail). */
    fun notifyPage(name: String, detail: String) {
        runOnUiThread {
            web.evaluateJavascript("window.dispatchEvent(new CustomEvent('$name', {detail: $detail}))", null)
        }
    }

    fun askPermissions() {
        val perms = mutableListOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
        if (Build.VERSION.SDK_INT >= 33) perms += Manifest.permission.NEARBY_WIFI_DEVICES
        requestPermissions(perms.toTypedArray(), 1)
    }

    fun keepAwake(on: Boolean) {
        if (on) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    fun askServer(problem: String?) {
        if (dialogOpen) return
        dialogOpen = true
        val input = EditText(this).apply {
            setText(prefs.getString("server", null) ?: BuildConfig.DEFAULT_SERVER.ifBlank { "http://" })
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine()
        }
        val pad = (20 * resources.displayMetrics.density).toInt()
        val box = FrameLayout(this).apply {
            setPadding(pad, 0, pad, 0)
            addView(input)
        }
        AlertDialog.Builder(this)
            .setTitle("Server von wifi-survey")
            .setMessage((problem?.let { "$it\n\n" } ?: "") +
                "Adresse der wifi-survey-Oberfläche im Heimnetz, z. B. http://192.168.178.180:8770 " +
                "(steht in der Oberfläche unter „Messen“)")
            .setView(box)
            .setPositiveButton("Öffnen") { _, _ ->
                val url = input.text.toString().trim()
                prefs.edit().putString("server", url).apply()
                open(url)
            }
            .setNegativeButton("Abbrechen", null)
            .setOnDismissListener { dialogOpen = false }
            .show()
    }
}
