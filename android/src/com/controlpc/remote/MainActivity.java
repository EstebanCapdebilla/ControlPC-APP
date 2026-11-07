package com.controlpc.remote;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.net.Uri;
import android.net.wifi.WifiManager;
import android.view.Display;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.security.SecureRandom;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Set;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * Contenedor nativo de la interfaz web del servidor.
 * Agrega lo que el navegador no permite: botones físicos de volumen, giroscopio,
 * mantener la pantalla encendida, vibración y descubrimiento automático del PC.
 */
public class MainActivity extends Activity implements SensorEventListener {
    private static final String LAUNCHER = "file:///android_asset/launcher.html";
    private static final int DISCOVERY_PORT = 8766;

    private WebView web;
    private SharedPreferences prefs;
    private final Handler ui = new Handler(Looper.getMainLooper());

    private volatile boolean onRemote = false;
    private volatile boolean captureVolume = false;
    private volatile String remoteHost = null;
    private boolean autoOpenUsed = false;
    private boolean fullscreen = false;

    private WifiManager.WifiLock wifiLock;
    private SensorManager sensors;
    private Sensor gyro;
    private boolean gyroOn = false;
    private long gyroLast = 0;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("rc", MODE_PRIVATE);
        getWindow().setStatusBarColor(0xFF0F1115);
        getWindow().setNavigationBarColor(0xFF181B22);
        sensors = (SensorManager) getSystemService(Context.SENSOR_SERVICE);
        gyro = sensors != null ? sensors.getDefaultSensor(Sensor.TYPE_GYROSCOPE) : null;
        setupWifiLock();
        preferHighRefreshRate();

        web = new WebView(this);
        web.setBackgroundColor(0xFF0F1115);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setTextZoom(100);
        web.addJavascriptInterface(new Bridge(), "AndroidRC");
        web.setWebChromeClient(new WebChromeClient()); // habilita confirm()/alert()
        web.setWebViewClient(new Client());
        setContentView(web);
        goHome(null);
    }

    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
            Uri u = r.getUrl();
            if ("file".equals(u.getScheme())) return false;
            if (remoteHost != null && remoteHost.equals(u.getHost())) return false;
            try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) { }
            return true;
        }

        @Override
        public void onPageFinished(WebView v, String url) {
            onRemote = url != null && url.startsWith("http");
            if (!onRemote) { captureVolume = false; setGyro(false); }
        }

        @Override
        public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
            if (r.isForMainFrame() && "http".equals(r.getUrl().getScheme())) {
                goHome("No se pudo conectar con el PC. ¿Está abierto el servidor?");
            }
        }
    }

    /** Se puede llamar desde cualquier hilo (p. ej. tras verificar el PC en segundo plano). */
    private void goHome(String message) {
        onRemote = false;
        captureVolume = false;
        remoteHost = null;
        setGyro(false);
        String url = LAUNCHER + (message != null ? "#" + Uri.encode(message) : "");
        ui.post(() -> {
            getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            web.loadUrl(url);
        });
    }

    private void js(String code) {
        ui.post(() -> web.evaluateJavascript(code, null));
    }

    // ------------------------------------------------------------------ teclas físicas
    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        int k = e.getKeyCode();
        if (onRemote && captureVolume && (k == KeyEvent.KEYCODE_VOLUME_UP || k == KeyEvent.KEYCODE_VOLUME_DOWN)) {
            if (e.getAction() == KeyEvent.ACTION_DOWN) {
                String dir = k == KeyEvent.KEYCODE_VOLUME_UP ? "up" : "down";
                web.evaluateJavascript("window.rcHardwareKey&&rcHardwareKey('" + dir + "'," + e.getRepeatCount() + ")", null);
            }
            return true; // no cambia el volumen del celular
        }
        return super.dispatchKeyEvent(e);
    }

    @Override
    public void onBackPressed() {
        if (onRemote) goHome(null);
        else super.onBackPressed();
    }

    @Override
    public void onConfigurationChanged(Configuration c) {
        super.onConfigurationChanged(c);
        if (fullscreen) applyFullscreen(true);
    }

    // ------------------------------------------------------------------ fluidez
    /**
     * Por defecto Android pone el Wi-Fi en ahorro de energía y agrupa los paquetes
     * (llegan al PC en ráfagas). El modo de baja latencia lo evita mientras la app
     * está en pantalla, que es justo cuando se usa como mouse.
     */
    @SuppressWarnings("deprecation")
    private void setupWifiLock() {
        try {
            WifiManager wm = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            if (wm == null) return;
            int mode = Build.VERSION.SDK_INT >= 29 ? WifiManager.WIFI_MODE_FULL_LOW_LATENCY
                    : WifiManager.WIFI_MODE_FULL_HIGH_PERF;
            wifiLock = wm.createWifiLock(mode, "ControlPC:latencia");
            wifiLock.setReferenceCounted(false);
        } catch (Exception ignored) { }
    }

    /** Usa la frecuencia más alta de la pantalla (90/120 Hz): más eventos táctiles por segundo. */
    @SuppressWarnings("deprecation")
    private void preferHighRefreshRate() {
        try {
            Display d = getWindowManager().getDefaultDisplay();
            Display.Mode cur = d.getMode(), best = cur;
            for (Display.Mode m : d.getSupportedModes()) {
                if (m.getPhysicalWidth() == cur.getPhysicalWidth() && m.getPhysicalHeight() == cur.getPhysicalHeight()
                        && m.getRefreshRate() > best.getRefreshRate()) best = m;
            }
            WindowManager.LayoutParams lp = getWindow().getAttributes();
            lp.preferredDisplayModeId = best.getModeId();
            lp.preferredRefreshRate = best.getRefreshRate();
            getWindow().setAttributes(lp);
        } catch (Exception ignored) { }
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (gyroOn && sensors != null) sensors.unregisterListener(this);
        try { if (wifiLock != null && wifiLock.isHeld()) wifiLock.release(); } catch (Exception ignored) { }
    }

    @Override
    protected void onResume() {
        super.onResume();
        try { if (wifiLock != null) wifiLock.acquire(); } catch (Exception ignored) { }
        if (gyroOn && sensors != null && gyro != null) sensors.registerListener(this, gyro, 8000);
        if (fullscreen) applyFullscreen(true);
    }

    @SuppressWarnings("deprecation")
    private void applyFullscreen(boolean on) {
        fullscreen = on;
        View d = getWindow().getDecorView();
        d.setSystemUiVisibility(on
                ? View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                : View.SYSTEM_UI_FLAG_VISIBLE);
    }

    // ------------------------------------------------------------------ giroscopio
    private void setGyro(boolean on) {
        ui.post(() -> {
            if (sensors == null || gyro == null || on == gyroOn) return;
            gyroOn = on;
            gyroLast = 0;
            if (on) sensors.registerListener(this, gyro, 8000); // ~125 Hz
            else sensors.unregisterListener(this);
        });
    }

    @Override
    public void onSensorChanged(SensorEvent ev) {
        if (!gyroOn || !onRemote) return;
        long t = ev.timestamp;
        if (gyroLast == 0) { gyroLast = t; return; }
        float dt = (t - gyroLast) / 1e9f;
        gyroLast = t;
        if (dt <= 0 || dt > 0.1f) return;
        float wx = dz(ev.values[0]), wy = dz(ev.values[1]), wz = dz(ev.values[2]);
        // Sirve con el celular plano o vertical: girar a los lados mueve en X, inclinar mueve en Y.
        float dx = -(wz + wy) * dt;
        float dy = -wx * dt;
        if (dx != 0 || dy != 0) web.evaluateJavascript("window.rcGyro&&rcGyro(" + dx + "," + dy + ")", null);
    }

    private static float dz(float v) { return Math.abs(v) < 0.015f ? 0 : v; }

    @Override
    public void onAccuracyChanged(Sensor s, int a) { }

    // ------------------------------------------------------------------ PCs guardados
    private JSONObject pcs() {
        try { return new JSONObject(prefs.getString("pcs", "{}")); } catch (Exception e) { return new JSONObject(); }
    }

    private void savePcs(JSONObject o) { prefs.edit().putString("pcs", o.toString()).apply(); }

    /**
     * Abre la página del PC. Si hay códigos guardados para esa dirección, primero el PC
     * debe demostrar que conoce alguno (sin enviarlo). Así, si otro equipo ocupa la IP
     * o se hace pasar por el PC, nunca recibe el código.
     */
    private void openPc(String host, int port, List<String> tokens) {
        if (tokens.isEmpty()) { load(host, port, null); return; }
        new Thread(() -> {
            String nonce = randomHex(16);
            String res = httpGet("http://" + host + ":" + port + "/api/prove?n=" + nonce, 2500);
            if (res == null) { goHome("No se pudo conectar con el PC en " + host + ". ¿Está abierto Control PC?"); return; }
            String proof;
            try { proof = new JSONObject(res).optString("proof"); } catch (Exception e) { proof = ""; }
            for (String t : tokens) {
                if (proofOk(t, nonce, proof)) { load(host, port, t); return; }
            }
            goHome("El equipo en " + host + " no pudo demostrar que es tu PC, así que no se le envió tu código. "
                    + "Si cambiaste el código del PC, reinstalaste o usas otro Windows, olvida ese PC (✕) y vincúlalo con el PIN.");
        }).start();
    }

    private void load(String host, int port, String token) {
        remoteHost = host;
        String url = "http://" + host + ":" + port + "/" + (token != null && !token.isEmpty() ? "?t=" + Uri.encode(token) : "");
        ui.post(() -> web.loadUrl(url));
    }

    private static List<String> single(String token) {
        List<String> l = new ArrayList<>();
        if (token != null && !token.isEmpty()) l.add(token);
        return l;
    }

    // ------------------------------------------------------------------ verificación del PC
    /** El PC firma (nonce + la IP desde la que le preguntamos) con el código de acceso. */
    private static boolean proofOk(String token, String nonce, String proof) {
        if (token == null || token.isEmpty() || proof == null || proof.isEmpty()) return false;
        for (String ip : localIPv4()) {
            if (constantEquals(hmacHex(token, "rcpc1|" + nonce + "|" + ip), proof)) return true;
        }
        return false;
    }

    private static String hmacHex(String key, String msg) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            return hex(mac.doFinal(msg.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) { return ""; }
    }

    private static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format("%02x", x & 0xFF));
        return sb.toString();
    }

    private static boolean constantEquals(String a, String b) {
        if (a.length() != b.length() || a.isEmpty()) return false;
        int r = 0;
        for (int i = 0; i < a.length(); i++) r |= a.charAt(i) ^ b.charAt(i);
        return r == 0;
    }

    private static String randomHex(int bytes) {
        byte[] b = new byte[bytes];
        new SecureRandom().nextBytes(b);
        return hex(b);
    }

    /** Direcciones IPv4 de este celular (Wi-Fi, punto de acceso...). */
    private static List<String> localIPv4() {
        List<String> out = new ArrayList<>();
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InetAddress a : Collections.list(ni.getInetAddresses())) {
                    if (a instanceof Inet4Address) out.add(a.getHostAddress());
                }
            }
        } catch (Exception ignored) { }
        return out;
    }

    /** null = no hubo conexión; "" = respondió con error. */
    private static String httpGet(String url, int timeoutMs) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(timeoutMs);
            c.setReadTimeout(timeoutMs);
            c.setUseCaches(false);
            if (c.getResponseCode() != 200) return "";
            try (InputStream in = c.getInputStream()) {
                ByteArrayOutputStream bo = new ByteArrayOutputStream();
                byte[] buf = new byte[4096];
                int n;
                while ((n = in.read(buf)) > 0 && bo.size() < 65536) bo.write(buf, 0, n);
                return new String(bo.toByteArray(), StandardCharsets.UTF_8);
            }
        } catch (Exception e) {
            return null;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    // ------------------------------------------------------------------ puente JS
    private class Bridge {
        @JavascriptInterface public String version() { return "1.2"; }

        @JavascriptInterface public String saved() {
            JSONObject o = pcs();
            try { o = new JSONObject().put("pcs", o).put("last", prefs.getString("last", "")).put("gyro", gyro != null); }
            catch (Exception ignored) { }
            return o.toString();
        }

        /** Primera apertura de la app: permite conectarse solo al último PC. */
        @JavascriptInterface public boolean autoOpen() {
            if (autoOpenUsed) return false;
            autoOpenUsed = true;
            return true;
        }

        @JavascriptInterface public void discover() {
            new Thread(MainActivity.this::runDiscovery).start();
        }

        @JavascriptInterface public void open(String id) {
            JSONObject pc = pcs().optJSONObject(id);
            if (pc == null) return;
            prefs.edit().putString("last", id).apply();
            openPc(pc.optString("host"), pc.optInt("port", 8765), single(pc.optString("token")));
        }

        @JavascriptInterface public void openAddress(String host, int port) {
            // Puede haber varios PCs guardados con la misma IP (p. ej. dos Windows en el mismo equipo):
            // se usa el código que el PC demuestre conocer.
            List<String> tokens = new ArrayList<>();
            JSONObject all = pcs();
            for (Iterator<String> it = all.keys(); it.hasNext(); ) {
                JSONObject pc = all.optJSONObject(it.next());
                if (pc != null && host.equals(pc.optString("host")) && port == pc.optInt("port")) {
                    String t = pc.optString("token");
                    if (!t.isEmpty() && !tokens.contains(t)) tokens.add(t);
                }
            }
            openPc(host, port, tokens);
        }

        /** La página del PC avisa que se conectó con éxito: se guarda para la próxima vez. */
        @JavascriptInterface public void remember(String id, String name, String host, int port, String token) {
            if (id == null || id.isEmpty()) return;
            JSONObject all = pcs();
            try {
                all.put(id, new JSONObject().put("name", name).put("host", host).put("port", port).put("token", token));
            } catch (Exception ignored) { }
            savePcs(all);
            prefs.edit().putString("last", id).apply();
        }

        @JavascriptInterface public void forget(String id) {
            JSONObject all = pcs();
            all.remove(id);
            savePcs(all);
        }

        @JavascriptInterface public void home() { goHome(null); }

        @JavascriptInterface public void setCaptureVolume(boolean on) { captureVolume = on; }

        @JavascriptInterface public void setKeepAwake(boolean on) {
            ui.post(() -> {
                if (on) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            });
        }

        @JavascriptInterface public void setFullscreen(boolean on) { ui.post(() -> applyFullscreen(on)); }

        @JavascriptInterface public boolean isFullscreen() { return fullscreen; }

        @JavascriptInterface public boolean hasGyro() { return gyro != null; }

        @JavascriptInterface public void gyro(boolean on) { setGyro(on); }

        @JavascriptInterface public void vibrate(int ms) {
            Vibrator v = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            if (v == null || ms <= 0) return;
            v.vibrate(VibrationEffect.createOneShot(Math.min(ms, 200), VibrationEffect.DEFAULT_AMPLITUDE));
        }

        @JavascriptInterface public void copy(String text) {
            ui.post(() -> {
                ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
                if (cm != null) cm.setPrimaryClip(ClipData.newPlainText("PC", text));
                if (Build.VERSION.SDK_INT < 33) Toast.makeText(MainActivity.this, "Copiado", Toast.LENGTH_SHORT).show();
            });
        }

        @JavascriptInterface public String paste() {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            if (cm == null || !cm.hasPrimaryClip() || cm.getPrimaryClip().getItemCount() == 0) return "";
            CharSequence t = cm.getPrimaryClip().getItemAt(0).coerceToText(MainActivity.this);
            return t == null ? "" : t.toString();
        }
    }

    // ------------------------------------------------------------------ descubrimiento UDP
    private void runDiscovery() {
        JSONArray found = new JSONArray();
        Set<String> seen = new HashSet<>();
        try (DatagramSocket sock = new DatagramSocket()) {
            sock.setBroadcast(true);
            sock.setSoTimeout(250);
            String nonce = randomHex(16);
            byte[] msg = ("RCPC_DISCOVER " + nonce).getBytes(StandardCharsets.US_ASCII);
            JSONObject saved = pcs();
            List<InetAddress> targets = broadcastAddresses();
            long end = System.currentTimeMillis() + 1600;
            int round = 0;
            byte[] buf = new byte[2048];
            while (System.currentTimeMillis() < end) {
                if (round < 3 && System.currentTimeMillis() > end - 1600 + round * 500L) {
                    for (InetAddress a : targets) {
                        try { sock.send(new DatagramPacket(msg, msg.length, a, DISCOVERY_PORT)); } catch (Exception ignored) { }
                    }
                    round++;
                }
                try {
                    DatagramPacket p = new DatagramPacket(buf, buf.length);
                    sock.receive(p);
                    JSONObject info = new JSONObject(new String(p.getData(), 0, p.getLength(), StandardCharsets.UTF_8));
                    String id = info.optString("id");
                    if (!"rcpc".equals(info.optString("app")) || seen.contains(id)) continue;
                    JSONObject known = saved.optJSONObject(id);
                    // PC ya vinculado: solo se cree la respuesta si viene firmada con su código.
                    // Si no, se ignora (no se cambia su dirección ni se marca "en la red").
                    if (known != null && !proofOk(known.optString("token"), nonce, info.optString("proof"))) continue;
                    seen.add(id);
                    String host = p.getAddress().getHostAddress();
                    info.remove("proof");
                    info.put("host", host);
                    found.put(info);
                    if (known != null) updateHost(id, host, info.optInt("port", 8765), info.optString("name"));
                } catch (SocketTimeoutException ignored) {
                } catch (Exception ignored) { }
            }
        } catch (Exception ignored) { }
        js("window.onDiscovered&&onDiscovered(" + found + ")");
    }

    /** Si el PC cambió de IP (DHCP), se actualiza sin volver a vincular. */
    private synchronized void updateHost(String id, String host, int port, String name) {
        JSONObject all = pcs();
        JSONObject pc = all.optJSONObject(id);
        if (pc == null) return;
        try { pc.put("host", host).put("port", port).put("name", name); } catch (Exception ignored) { }
        savePcs(all);
    }

    private static List<InetAddress> broadcastAddresses() {
        List<InetAddress> out = new ArrayList<>();
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InterfaceAddress ia : ni.getInterfaceAddresses()) {
                    if (ia.getBroadcast() != null && !out.contains(ia.getBroadcast())) out.add(ia.getBroadcast());
                }
            }
        } catch (Exception ignored) { }
        try { out.add(InetAddress.getByName("255.255.255.255")); } catch (Exception ignored) { }
        return out;
    }
}
