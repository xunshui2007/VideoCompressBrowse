package com.gpstest

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.location.GnssStatus
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.concurrent.TimeUnit

class GpsService : Service() {

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var locationManager: LocationManager
    private lateinit var wifiManager: WifiManager
    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .build()
    private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()
    private val handler = Handler(Looper.getMainLooper())
    private var sendRunnable: Runnable? = null
    private var serverUrl = ""
    private var currentLocation: Location? = null
    private var satelliteCount = 0
    private var satellites: List<SatelliteInfo> = emptyList()
    private var gnssCallback: GnssStatus.Callback? = null

    private val locationListener = object : LocationListener {
        override fun onLocationChanged(location: Location) { currentLocation = location }
        override fun onStatusChanged(p0: String?, p1: Int, p2: android.os.Bundle?) {}
        override fun onProviderEnabled(p0: String) {}
        override fun onProviderDisabled(p0: String) {}
    }

    override fun onCreate() {
        super.onCreate()
        locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        createNotificationChannel()
        startLocationUpdates()
        setupGnssCallback()
        startForeground(NOTIFY_ID, buildNotification("GPS 监测中…"))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        serverUrl = intent?.getStringExtra("server_url") ?: ""
        if (serverUrl.isNotEmpty()) startSending()
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        sendRunnable?.let { handler.removeCallbacks(it) }
        try { locationManager.removeUpdates(locationListener) } catch (_: Exception) {}
        try { gnssCallback?.let { locationManager.unregisterGnssStatusCallback(it) } } catch (_: Exception) {}
        super.onDestroy()
    }

    private fun startLocationUpdates() {
        try {
            if (locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER))
                locationManager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 500, 0f, locationListener, Looper.getMainLooper())
            if (locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER))
                locationManager.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, 500, 0f, locationListener, Looper.getMainLooper())
            val last = locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER)
                ?: locationManager.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
            if (last != null) currentLocation = last
        } catch (_: SecurityException) {}
    }

    private fun setupGnssCallback() {
        gnssCallback = object : GnssStatus.Callback() {
            override fun onSatelliteStatusChanged(status: GnssStatus) {
                val list = mutableListOf<SatelliteInfo>()
                var used = 0
                for (i in 0 until status.satelliteCount) {
                    val u = status.usedInFix(i)
                    if (u) used++
                    val freq = status.getCarrierFrequencyHz(i)
                    list.add(SatelliteInfo(status.getSvid(i), status.getCn0DbHz(i), u,
                        when (status.getConstellationType(i)) {
                            GnssStatus.CONSTELLATION_GPS -> "GPS"
                            GnssStatus.CONSTELLATION_GLONASS -> "GLO"
                            GnssStatus.CONSTELLATION_BEIDOU -> "BDS"
                            GnssStatus.CONSTELLATION_GALILEO -> "GAL"
                            GnssStatus.CONSTELLATION_QZSS -> "QZSS"
                            GnssStatus.CONSTELLATION_IRNSS -> "IRN"
                            GnssStatus.CONSTELLATION_SBAS -> "SBAS"
                            else -> "?"
                        }, freq))
                }
                satellites = list.sortedByDescending { it.cn0 }
                satelliteCount = used
                updateNotification("卫星: $used/${status.satelliteCount}")
            }
        }
        try { locationManager.registerGnssStatusCallback(gnssCallback!!, handler) } catch (_: SecurityException) {}
    }

    private fun startSending() {
        sendRunnable = object : Runnable {
            override fun run() {
                sendData()
                handler.postDelayed(this, 1000)
            }
        }
        handler.post(sendRunnable!!)
    }

    private fun sendData() {
        serviceScope.launch {
            val loc = currentLocation
            val wifi = wifiManager.connectionInfo
            val json = JSONObject().apply {
                put("timestamp", System.currentTimeMillis())
                put("satellites", satelliteCount)
                put("satellites_detail", JSONArray(satellites.map {
                    JSONObject().apply {
                        put("svid", it.svid); put("cn0", it.cn0.toDouble())
                        put("used", it.usedInFix); put("const", it.constellation)
                        if (it.frequencyHz > 0) put("freq", it.frequencyHz.toDouble())
                    }
                }))
                if (loc != null) {
                    put("latitude", loc.latitude); put("longitude", loc.longitude)
                    put("altitude", if (loc.hasAltitude()) loc.altitude else JSONObject.NULL)
                    put("accuracy", if (loc.hasAccuracy()) loc.accuracy else JSONObject.NULL)
                    put("speed", if (loc.hasSpeed()) loc.speed else JSONObject.NULL)
                    put("bearing", if (loc.hasBearing()) loc.bearing else JSONObject.NULL)
                    put("provider", loc.provider ?: "?")
                }
                if (wifi != null) {
                    put("wifi_ssid", wifi.ssid.removeSurrounding("\""))
                    put("wifi_rssi", wifi.rssi); put("wifi_frequency", wifi.frequency)
                }
                put("phone_ip", getLocalIpAddress())
            }
            try {
                val body = json.toString().toRequestBody(JSON_MEDIA)
                val request = Request.Builder().url(serverUrl).post(body).build()
                withContext(Dispatchers.IO) { client.newCall(request).execute() }
            } catch (_: Exception) {}
        }
    }

    private fun getLocalIpAddress(): String {
        try {
            val intfs = NetworkInterface.getNetworkInterfaces()
            while (intfs.hasMoreElements()) {
                val intf = intfs.nextElement()
                if (intf.isLoopback || !intf.isUp) continue
                val addrs = intf.inetAddresses
                while (addrs.hasMoreElements()) {
                    val a = addrs.nextElement()
                    if (a is Inet4Address && !a.isLoopbackAddress) return a.hostAddress ?: "?"
                }
            }
        } catch (_: Exception) {}
        return "?"
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(CHANNEL_ID, "GPS 监测", NotificationManager.IMPORTANCE_LOW).apply {
                setShowBadge(false)
            }
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(ch)
        }
    }

    private fun buildNotification(text: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("GPS 信号监测")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun updateNotification(text: String) {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIFY_ID, buildNotification(text))
    }

    companion object {
        private const val CHANNEL_ID = "gps_monitor"
        private const val NOTIFY_ID = 1001
        fun start(context: Context, serverUrl: String) {
            val intent = Intent(context, GpsService::class.java).apply { putExtra("server_url", serverUrl) }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                context.startForegroundService(intent)
            else
                context.startService(intent)
        }
        fun stop(context: Context) {
            context.stopService(Intent(context, GpsService::class.java))
        }
    }
}
