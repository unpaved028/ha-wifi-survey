package io.github.unpaved028.wifisurvey

import android.Manifest
import android.app.job.JobInfo
import android.app.job.JobScheduler
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.net.wifi.ScanResult
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.abs

/**
 * Hintergrundmodus „findbar“ (Entscheidung 0010): Das Handy meldet dem Server einen WLAN-Scan, wenn es ruht.
 * Mit dem Scan sieht die Suche alle Zugangspunkte statt nur des einen, an dem das Handy hängt.
 *
 * Sparsam mit dem Akku:
 * - Android startet die Prüfung höchstens alle 15 Minuten (Jobplaner, nur im WLAN, gebündelt mit anderen Apps;
 *   ruht das Handy lange, schiebt Android sie im Tiefschlaf noch weiter hinaus).
 * - Außerhalb des Hauses (unbekannter Zugangspunkt) endet die Prüfung sofort, ohne Scan.
 * - Ruhe erkennen ohne Scan: Bildschirm aus oder am Ladekabel, dazu zweimal hintereinander (10–60 min Abstand)
 *   derselbe Zugangspunkt mit fast gleichem Signal. Beides kennt Android ohnehin.
 * - Gescannt und gemeldet wird nur, wenn sich seit der letzten Meldung etwas geändert hat; frische
 *   Scan-Ergebnisse von Android haben Vorrang. Kein GPS, kein Bluetooth, keine Dauerverbindung.
 * - Im Energiesparmodus setzt die Prüfung aus.
 * Gemeldet werden nur Zugangspunkte des Hauses, ohne Netznamen; fremde Netze verlassen das Handy nicht.
 */
class Findable(private val ctx: Context) {
    companion object {
        private const val JOB_ID = 4711
        private const val PERIOD_MS = 15 * 60 * 1000L
        private const val FLEX_MS = 5 * 60 * 1000L
        private const val STILL_DB = 4                          // so wenig schwankt das Signal, wenn das Handy liegt
        private const val CHANGED_DB = 6                        // so viel Änderung seit der letzten Meldung: neu melden
        private const val GAP_MIN_MS = 10 * 60 * 1000L          // zwei Prüfungen mindestens so weit auseinander
        private const val GAP_MAX_MS = 60 * 60 * 1000L          // ältere Prüfung belegt keine Ruhe mehr
        private const val REPEAT_MS = 12 * 60 * 60 * 1000L      // auch ohne Änderung spätestens nach 12 h melden
        private const val BSSIDS_MAX_AGE_MS = 24 * 60 * 60 * 1000L
        private const val SCAN_WAIT_MS = 15_000L
        private const val SCAN_MAX_AGE_MS = 30 * 60 * 1000L

        fun prefs(ctx: Context): SharedPreferences = ctx.getSharedPreferences("wifi-survey", Context.MODE_PRIVATE)

        fun enabled(ctx: Context) = prefs(ctx).getBoolean("findable", false)

        fun schedule(ctx: Context) {
            val job = JobInfo.Builder(JOB_ID, ComponentName(ctx, FindableJob::class.java))
                .setPeriodic(PERIOD_MS, FLEX_MS)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_UNMETERED)
                .setPersisted(true)
                .build()
            ctx.getSystemService(JobScheduler::class.java).schedule(job)
        }

        fun cancel(ctx: Context) = ctx.getSystemService(JobScheduler::class.java).cancel(JOB_ID)

        fun scheduled(ctx: Context) = ctx.getSystemService(JobScheduler::class.java).getPendingJob(JOB_ID) != null

        fun norm(mac: String?) = (mac ?: "").lowercase().filter { it in "0123456789abcdef" }
    }

    private val wifi = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
    private val p = prefs(ctx)

    /** Eine Prüfung, Ergebnis als kurzer Text für die Anzeige. force: sofort melden (Knopf in der App, Vordergrund). */
    fun check(force: Boolean): String {
        val result = try {
            run(force)
        } catch (e: Exception) {
            "Fehler: ${e.message ?: e.javaClass.simpleName}"
        }
        p.edit().putString("findable_status", result).putLong("findable_status_t", System.currentTimeMillis()).apply()
        return result
    }

    /** Hintergrundmodus aus: gespeicherte Meldung auf dem Server löschen. */
    fun forget(): String = try {
        val server = server() ?: return "kein Server eingetragen"
        http("DELETE", "$server/api/findable/report", null)
        p.edit().remove("report_bssid").remove("report_rssi").remove("report_t").apply()
        "aus, Meldung auf dem Server gelöscht"
    } catch (e: Exception) {
        "aus (Meldung auf dem Server nicht gelöscht: ${e.message})"
    }

    private fun run(force: Boolean): String {
        if (!force && !enabled(ctx)) return "aus"
        val power = ctx.getSystemService(PowerManager::class.java)
        if (!force && power.isPowerSaveMode) return "Energiesparmodus: ausgesetzt"
        if (!locationAllowed(background = !force)) return "Standort im Hintergrund nicht erlaubt"
        val server = server() ?: return "kein Server eingetragen"
        @Suppress("DEPRECATION")
        val info = wifi.connectionInfo
        val bssid = norm(info?.bssid)
        val rssi = info?.rssi ?: -127
        if (bssid == "020000000000") return "Zugangspunkt verborgen: Standort aus oder im Hintergrund nicht erlaubt"
        if (bssid.length != 12 || rssi !in -110..-10) return "nicht im WLAN"
        val known = knownBssids(server)
        if (bssid !in known) return "nicht im WLAN des Hauses"

        val now = System.currentTimeMillis()
        val prevB = p.getString("check_bssid", "") ?: ""
        val prevT = p.getLong("check_t", 0L)
        val same = prevB == bssid && abs(p.getInt("check_rssi", 0) - rssi) <= STILL_DB && now - prevT in 0..GAP_MAX_MS
        val restSince = if (same && p.getLong("rest_since", 0L) > 0) p.getLong("rest_since", 0L) else now
        p.edit().putString("check_bssid", bssid).putInt("check_rssi", rssi).putLong("check_t", now)
            .putLong("rest_since", restSince).apply()
        if (!force) {
            if (power.isInteractive && !charging()) return "in Benutzung"
            if (!same || now - restSince < GAP_MIN_MS) return "Ruhe noch nicht bestätigt"
            val repSame = p.getString("report_bssid", "") == bssid && abs(p.getInt("report_rssi", 0) - rssi) <= CHANGED_DB
            if (repSame && now - p.getLong("report_t", 0L) < REPEAT_MS) return "liegt wie bei der letzten Meldung"
        }

        val results = scan(known, if (force) 2 * 60 * 1000L else minOf(now - restSince, SCAN_MAX_AGE_MS))
        val nowUs = SystemClock.elapsedRealtime() * 1000
        val scan = JSONArray()
        for (r in results) {
            scan.put(JSONObject().put("bssid", r.BSSID ?: "").put("rssi", r.level).put("frequency", r.frequency)
                .put("age_ms", (nowUs - r.timestamp) / 1000))
        }
        val body = JSONObject()
            .put("device", Build.MODEL)
            .put("app_version", BuildConfig.VERSION_NAME)
            .put("still_s", (now - restSince) / 1000)
            .put("connection", JSONObject().put("bssid", info?.bssid ?: "").put("rssi", rssi)
                .put("frequency", info?.frequency ?: 0).put("link_mbps", info?.linkSpeed ?: 0))
            .put("scan", scan)
        val res = JSONObject(http("POST", "$server/api/findable/report", body.toString()))
        p.edit().putString("report_bssid", bssid).putInt("report_rssi", rssi).putLong("report_t", now)
            .putString("report_name", res.optString("name")).apply()
        return "gemeldet: ${res.optInt("n")} Werte, als „${res.optString("name")}“"
    }

    private fun server(): String? =
        (p.getString("server", null) ?: BuildConfig.DEFAULT_SERVER).trim().trimEnd('/').ifBlank { null }

    private fun locationAllowed(background: Boolean): Boolean {
        val granted = { perm: String -> ctx.checkSelfPermission(perm) == PackageManager.PERMISSION_GRANTED }
        if (!granted(Manifest.permission.ACCESS_FINE_LOCATION)) return false
        return !background || Build.VERSION.SDK_INT < 29 || granted(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
    }

    private fun charging() = ctx.getSystemService(BatteryManager::class.java).isCharging

    /** BSSIDs der Zugangspunkte des Hauses (vom Server, einmal am Tag neu). */
    private fun knownBssids(server: String): Set<String> {
        val cached = p.getStringSet("bssids", emptySet()) ?: emptySet()
        if (cached.isNotEmpty() && System.currentTimeMillis() - p.getLong("bssids_t", 0L) < BSSIDS_MAX_AGE_MS) return cached
        return try {
            val aps = JSONObject(http("GET", "$server/api/survey/aps", null)).getJSONArray("aps")
            val out = mutableSetOf<String>()
            for (i in 0 until aps.length()) {
                val b = aps.getJSONObject(i).getJSONArray("bssids")
                for (j in 0 until b.length()) out += norm(b.getString(j))
            }
            p.edit().putStringSet("bssids", out).putLong("bssids_t", System.currentTimeMillis()).apply()
            out
        } catch (e: Exception) {
            cached    // Server gerade nicht erreichbar: letzter Stand
        }
    }

    /** Frische Scan-Ergebnisse der Zugangspunkte des Hauses; nur wenn nötig ein eigener Scan (Android erlaubt
     *  im Hintergrund ohnehin nur einen je 30 Minuten). Gastnetze desselben Geräts über die ersten fünf Bytes. */
    @Suppress("DEPRECATION")
    private fun scan(known: Set<String>, maxAgeMs: Long): List<ScanResult> {
        val prefixes = known.map { it.take(10) }.toSet()
        fun fresh(): List<ScanResult> {
            val nowUs = SystemClock.elapsedRealtime() * 1000
            return try {
                wifi.scanResults.filter { r ->
                    val b = norm(r.BSSID)
                    nowUs - r.timestamp <= maxAgeMs * 1000 && r.level in -110..-10 && (b in known || b.take(10) in prefixes)
                }
            } catch (e: SecurityException) {
                emptyList()
            }
        }
        val have = fresh()
        if (have.size >= 2) return have
        val done = CountDownLatch(1)
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) = done.countDown()
        }
        val filter = IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION)
        if (Build.VERSION.SDK_INT >= 33) ctx.registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED)
        else ctx.registerReceiver(receiver, filter)
        try {
            val started = try {
                wifi.startScan()
            } catch (e: SecurityException) {
                false
            }
            if (started) done.await(SCAN_WAIT_MS, TimeUnit.MILLISECONDS)
        } finally {
            ctx.unregisterReceiver(receiver)
        }
        return fresh()
    }

    private fun http(method: String, url: String, body: String?): String {
        val con = URL(url).openConnection() as HttpURLConnection
        try {
            con.requestMethod = method
            con.connectTimeout = 10_000
            con.readTimeout = 20_000
            if (body != null) {
                con.doOutput = true
                con.setRequestProperty("Content-Type", "application/json")
                con.outputStream.use { it.write(body.toByteArray()) }
            }
            val ok = con.responseCode in 200..299
            val text = (if (ok) con.inputStream else con.errorStream)?.bufferedReader()?.use { it.readText() } ?: ""
            if (!ok) {
                val detail = try {
                    JSONObject(text).optString("detail", text)
                } catch (e: Exception) {
                    text
                }
                throw IllegalStateException("Server ${con.responseCode}: ${detail.take(200)}")
            }
            return text
        } finally {
            con.disconnect()
        }
    }
}
