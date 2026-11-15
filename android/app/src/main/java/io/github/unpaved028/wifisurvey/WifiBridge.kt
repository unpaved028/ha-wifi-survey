package io.github.unpaved028.wifisurvey

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.LocationManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.SystemClock
import android.provider.Settings
import android.webkit.JavascriptInterface
import org.json.JSONArray
import org.json.JSONObject

/**
 * Brücke für die Web-Oberfläche (window.WifiSurveyApp). Alle Werte sind Sicht des Handys:
 * Signal in dBm, Frequenz in MHz. Android drosselt Scans (4 je 2 Minuten im Vordergrund);
 * die Drosselung lässt sich in den Entwickleroptionen abschalten.
 */
class WifiBridge(private val activity: MainActivity) {
    private val wifi = activity.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager

    @JavascriptInterface
    fun version(): String = BuildConfig.VERSION_NAME

    @JavascriptInterface
    fun permissions(): String {
        val granted = { p: String -> activity.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED }
        val location = activity.getSystemService(LocationManager::class.java)
        return JSONObject()
            .put("location", granted(Manifest.permission.ACCESS_FINE_LOCATION))
            .put("nearby", Build.VERSION.SDK_INT < 33 || granted(Manifest.permission.NEARBY_WIFI_DEVICES))
            .put("location_enabled", Build.VERSION.SDK_INT < 28 || location.isLocationEnabled)
            .put("wifi_enabled", wifi.isWifiEnabled)
            .toString()
    }

    @JavascriptInterface
    fun requestPermissions() = activity.runOnUiThread { activity.askPermissions() }

    @JavascriptInterface
    fun openLocationSettings() = activity.runOnUiThread {
        activity.startActivity(Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS))
    }

    @JavascriptInterface
    fun changeServer() = activity.runOnUiThread { activity.askServer(null) }

    @JavascriptInterface
    fun keepAwake(on: Boolean) = activity.runOnUiThread { activity.keepAwake(on) }

    /** Verbundener Zugangspunkt: BSSID, Signal, Frequenz, Datenrate. */
    @Suppress("DEPRECATION")
    @JavascriptInterface
    fun connection(): String {
        val info = wifi.connectionInfo ?: return "null"
        val o = JSONObject()
            .put("bssid", info.bssid ?: "")
            .put("ssid", (info.ssid ?: "").trim('"'))
            .put("rssi", info.rssi)
            .put("frequency", info.frequency)
            .put("link_mbps", info.linkSpeed)
        if (Build.VERSION.SDK_INT >= 29) o.put("rx_mbps", info.rxLinkSpeedMbps).put("tx_mbps", info.txLinkSpeedMbps)
        if (Build.VERSION.SDK_INT >= 30) o.put("standard", info.wifiStandard)
        return o.toString()
    }

    /** Scan anstoßen; false, wenn Android ihn gerade drosselt oder die Berechtigung fehlt. */
    @Suppress("DEPRECATION")
    @JavascriptInterface
    fun startScan(): Boolean = try {
        wifi.startScan()
    } catch (e: SecurityException) {
        false
    }

    /** Hintergrundmodus „findbar“ (Entscheidung 0010): Zustand für die Oberfläche. */
    @JavascriptInterface
    fun findable(): String {
        val p = Findable.prefs(activity)
        val background = Build.VERSION.SDK_INT < 29 ||
            activity.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION) == PackageManager.PERMISSION_GRANTED
        return JSONObject()
            .put("enabled", Findable.enabled(activity))
            .put("scheduled", Findable.scheduled(activity))
            .put("background_location", background)
            .put("status", p.getString("findable_status", "") ?: "")
            .put("status_t", p.getLong("findable_status_t", 0L))
            .put("report_t", p.getLong("report_t", 0L))
            .put("report_name", p.getString("report_name", "") ?: "")
            .put("period_min", 15)
            .toString()
    }

    /** Ein- oder ausschalten; aus: auch die Meldung auf dem Server löschen. */
    @JavascriptInterface
    fun setFindable(on: Boolean) {
        Findable.prefs(activity).edit().putBoolean("findable", on).apply()
        if (on) {
            Findable.schedule(activity)
            activity.notifyPage("findable", findable())
        } else {
            Findable.cancel(activity)
            Thread {
                val msg = Findable(activity).forget()
                Findable.prefs(activity).edit().putString("findable_status", msg)
                    .putLong("findable_status_t", System.currentTimeMillis()).apply()
                activity.notifyPage("findable", findable())
            }.start()
        }
    }

    /** Sofort prüfen und melden (ohne Ruhe-Prüfung), Ergebnis als Ereignis „findable“. */
    @JavascriptInterface
    fun findableNow() {
        Thread {
            Findable(activity).check(force = true)
            activity.notifyPage("findable", findable())
        }.start()
    }

    @JavascriptInterface
    fun requestBackgroundLocation() = activity.runOnUiThread { activity.askBackgroundLocation() }

    /** Letzte Scan-Ergebnisse mit Alter in Millisekunden. */
    @Suppress("DEPRECATION")
    @JavascriptInterface
    fun scanResults(): String {
        val out = JSONArray()
        val nowUs = SystemClock.elapsedRealtime() * 1000
        try {
            for (r in wifi.scanResults) {
                out.put(
                    JSONObject()
                        .put("bssid", r.BSSID ?: "")
                        .put("ssid", r.SSID ?: "")
                        .put("rssi", r.level)
                        .put("frequency", r.frequency)
                        .put("age_ms", (nowUs - r.timestamp) / 1000)
                )
            }
        } catch (e: SecurityException) {
            return "[]"
        }
        return out.toString()
    }
}
