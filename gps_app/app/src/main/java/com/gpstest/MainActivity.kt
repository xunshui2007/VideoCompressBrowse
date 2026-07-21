package com.gpstest

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.GnssStatus
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.content.res.ColorStateList
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.gpstest.databinding.ActivityMainBinding
import kotlinx.coroutines.Dispatchers
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
import java.util.Locale
import java.util.concurrent.TimeUnit

data class SatelliteInfo(
    val svid: Int,
    val cn0: Float,
    val usedInFix: Boolean,
    val constellation: String,
    val frequencyHz: Float = 0f
)

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var locationManager: LocationManager
    private lateinit var wifiManager: WifiManager
    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.SECONDS)
        .build()

    private var isSending = false
    private var gnssCallback: GnssStatus.Callback? = null
    private var satelliteCount = 0
    private var satellites: List<SatelliteInfo> = emptyList()
    private var currentLocation: Location? = null
    private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()
    private val mainHandler = Handler(Looper.getMainLooper())
    private var sendRunnable: Runnable? = null
    private val SEND_INTERVAL_MS = 1000L

    private val locationListener = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            currentLocation = location
            updateGpsUi(location)
        }

        override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
        override fun onProviderEnabled(provider: String) {}
        override fun onProviderDisabled(provider: String) {}
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager
        wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager

        checkPermissions()
        updateWifiInfo()
        binding.btnToggleSend.setOnClickListener { toggleSending() }
        requestNotificationPermission()
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 200)
            }
        }
    }

    private fun checkPermissions() {
        val needed = mutableListOf<String>()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            != PackageManager.PERMISSION_GRANTED
        ) needed.add(Manifest.permission.ACCESS_FINE_LOCATION)

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION)
            != PackageManager.PERMISSION_GRANTED
        ) needed.add(Manifest.permission.ACCESS_COARSE_LOCATION)

        if (needed.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, needed.toTypedArray(), 100)
        } else {
            startLocationUpdates()
            setupGnssCallback()
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 100) {
            var allGranted = true
            for (r in grantResults) {
                if (r != PackageManager.PERMISSION_GRANTED) allGranted = false
            }
            if (allGranted) {
                startLocationUpdates()
                setupGnssCallback()
            } else {
                Toast.makeText(this, "需要位置权限才能读取GPS", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun startLocationUpdates() {
        try {
            val gpsEnabled = locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)
            val networkEnabled = locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)

            if (gpsEnabled) {
                locationManager.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER, 500, 0f, locationListener, Looper.getMainLooper()
                )
            }
            if (networkEnabled) {
                locationManager.requestLocationUpdates(
                    LocationManager.NETWORK_PROVIDER, 500, 0f, locationListener, Looper.getMainLooper()
                )
            }

            val lastGps = locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER)
            val lastNetwork = locationManager.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
            val lastLocation = lastGps ?: lastNetwork
            if (lastLocation != null) {
                currentLocation = lastLocation
                updateGpsUi(lastLocation)
            }

            updateGpsStatus(gpsEnabled || networkEnabled)
        } catch (e: SecurityException) {
            Toast.makeText(this, "权限错误: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    private fun setupGnssCallback() {
        gnssCallback = object : GnssStatus.Callback() {
            override fun onSatelliteStatusChanged(status: GnssStatus) {
                val list = mutableListOf<SatelliteInfo>()
                var count = 0
                var usedCount = 0
                for (i in 0 until status.satelliteCount) {
                    count++
                    val used = status.usedInFix(i)
                    if (used) usedCount++
                    list.add(SatelliteInfo(
                        svid = status.getSvid(i),
                        cn0 = status.getCn0DbHz(i),
                        usedInFix = used,
                        constellation = when (status.getConstellationType(i)) {
                            GnssStatus.CONSTELLATION_GPS -> "GPS"
                            GnssStatus.CONSTELLATION_GLONASS -> "GLO"
                            GnssStatus.CONSTELLATION_BEIDOU -> "BDS"
                            GnssStatus.CONSTELLATION_GALILEO -> "GAL"
                            GnssStatus.CONSTELLATION_QZSS -> "QZSS"
                            GnssStatus.CONSTELLATION_IRNSS -> "IRN"
                            GnssStatus.CONSTELLATION_SBAS -> "SBAS"
                            else -> "?"
                        }
                    ))
                }
                satellites = list.sortedByDescending { it.cn0 }
                satelliteCount = usedCount
                binding.tvSatellites.text = "$usedCount / $count"
            }
        }
        try {
            locationManager.registerGnssStatusCallback(gnssCallback!!, mainHandler)
        } catch (_: SecurityException) {}
    }

    private fun updateGpsUi(location: Location) {
        val provider = location.provider ?: "?"
        val accuracy = location.accuracy
        val gpsFix = accuracy > 0 && accuracy < 100

        binding.apply {
            tvGpsStatus.text = if (gpsFix) "$provider ✓ 已定位" else "$provider 定位中…"
            tvGpsStatus.setTextColor(
                ContextCompat.getColor(
                    this@MainActivity,
                    if (gpsFix) R.color.gps_fix else R.color.gps_no_fix
                )
            )

            tvLatitude.text = String.format(Locale.US, "%.6f°", location.latitude)
            tvLongitude.text = String.format(Locale.US, "%.6f°", location.longitude)

            if (location.hasAltitude()) {
                tvAltitude.text = String.format(Locale.US, "%.1f m", location.altitude)
            } else {
                tvAltitude.text = "N/A"
            }

            if (location.hasAccuracy()) {
                tvAccuracy.text = String.format(Locale.US, "%.1f m", location.accuracy)
            } else {
                tvAccuracy.text = "N/A"
            }

            if (location.hasSpeed()) {
                tvSpeed.text = String.format(Locale.US, "%.1f m/s", location.speed)
            } else {
                tvSpeed.text = "N/A"
            }
        }
    }

    private fun updateGpsStatus(enabled: Boolean) {
        if (!enabled) {
            binding.tvGpsStatus.text = "GPS 未开启"
            binding.tvGpsStatus.setTextColor(ContextCompat.getColor(this, R.color.gps_no_fix))
        }
    }

    private fun updateWifiInfo() {
        val wifiInfo = wifiManager.connectionInfo ?: return
        val ssid = wifiInfo.ssid.removeSurrounding("\"")
        val rssi = wifiInfo.rssi
        val freq = wifiInfo.frequency
        val rssiPct = WifiManager.calculateSignalLevel(rssi, 101)

        binding.apply {
            tvWifiSsid.text = ssid.ifEmpty { "<未连接>" }
            tvWifiRssi.text = "$rssi dBm ($rssiPct%)"

            val rssiColor = when {
                rssi >= -67 -> R.color.wifi_good
                rssi >= -80 -> R.color.wifi_fair
                else -> R.color.wifi_weak
            }
            tvWifiRssi.setTextColor(ContextCompat.getColor(this@MainActivity, rssiColor))

            tvWifiFreq.text = "${freq} MHz"
            tvWifiIp.text = "本机 IP: ${getLocalIpAddress()}"
        }
    }

    private fun getLocalIpAddress(): String {
        try {
            val interfaces = NetworkInterface.getNetworkInterfaces()
            while (interfaces.hasMoreElements()) {
                val intf = interfaces.nextElement()
                if (intf.isLoopback || !intf.isUp) continue
                val addrs = intf.inetAddresses
                while (addrs.hasMoreElements()) {
                    val addr = addrs.nextElement()
                    if (addr is Inet4Address && !addr.isLoopbackAddress) {
                        return addr.hostAddress ?: "?"
                    }
                }
            }
        } catch (_: Exception) {}
        return "?"
    }

    private fun toggleSending() {
        if (!isSending) {
            val ip = binding.etServerIp.text.toString().trim()
            val port = binding.etServerPort.text.toString().trim()
            if (ip.isEmpty() || port.isEmpty()) {
                Toast.makeText(this, "请输入电脑 IP 和端口", Toast.LENGTH_SHORT).show(); return
            }
            if (!ip.matches(Regex("^\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}$"))) {
                Toast.makeText(this, "IP 格式不正确", Toast.LENGTH_SHORT).show(); return
            }
            isSending = true
            binding.btnToggleSend.text = getString(R.string.stop_send)
            binding.btnToggleSend.backgroundTintList = ColorStateList.valueOf(
                ContextCompat.getColor(this, R.color.gps_no_fix))
            binding.tvSendStatus.text = "后台运行中…"
            binding.tvSendStatus.setTextColor(ContextCompat.getColor(this, R.color.gps_fix))
            GpsService.start(this, "http://$ip:$port/api/gps")
        } else {
            isSending = false
            binding.btnToggleSend.text = getString(R.string.start_send)
            binding.btnToggleSend.backgroundTintList = ColorStateList.valueOf(
                ContextCompat.getColor(this, R.color.primary))
            binding.tvSendStatus.text = getString(R.string.disconnected)
            binding.tvSendStatus.setTextColor(ContextCompat.getColor(this, R.color.text_secondary))
            GpsService.stop(this)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        isSending = false
        sendRunnable?.let { mainHandler.removeCallbacks(it) }
        try {
            locationManager.removeUpdates(locationListener)
        } catch (_: Exception) {}
        try { gnssCallback?.let { locationManager.unregisterGnssStatusCallback(it) } } catch (_: Exception) {}
    }
}
