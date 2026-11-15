package io.github.unpaved028.wifisurvey

import android.app.job.JobParameters
import android.app.job.JobService

/** Prüfung des Hintergrundmodus „findbar“, vom Jobplaner von Android gestartet (siehe Findable). */
class FindableJob : JobService() {
    @Volatile
    private var worker: Thread? = null

    override fun onStartJob(params: JobParameters): Boolean {
        worker = Thread {
            Findable(this).check(force = false)
            jobFinished(params, false)
        }.apply { start() }
        return true   // läuft im eigenen Thread weiter (Netz, Scan)
    }

    override fun onStopJob(params: JobParameters): Boolean {
        worker?.interrupt()
        return false  // regelmäßige Prüfung: einfach beim nächsten Mal
    }
}
