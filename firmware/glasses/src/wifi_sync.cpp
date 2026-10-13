#include "wifi_sync.h"

#include <SD.h>
#include <cstring>
#include <Update.h>
#include <WebServer.h>
#include <WiFi.h>
#include <esp_random.h>
#include <uri/UriBraces.h>

#include "config.h"

namespace wifi_sync {

namespace {
WebServer* g_server = nullptr;
CommandHandler g_handler = nullptr;
volatile bool g_active = false;
volatile bool g_serving = false;
TaskHandle_t g_task = nullptr;
SemaphoreHandle_t g_taskDone = nullptr;
char g_ssid[32] = {0};
char g_pass[16] = {0};
char g_ip[16] = {0};
char g_busy[48] = {0};                 // basename of the file being recorded
portMUX_TYPE g_busyMux = portMUX_INITIALIZER_UNLOCKED;
enum class Ota : uint8_t { Idle, Writing, Refused, Failed };
Ota g_ota = Ota::Idle;

bool isBusy(const String& name) {
  portENTER_CRITICAL(&g_busyMux);
  const bool busy = g_busy[0] && name == g_busy;
  portEXIT_CRITICAL(&g_busyMux);
  return busy;
}

bool recording() {
  portENTER_CRITICAL(&g_busyMux);
  const bool r = g_busy[0] != '\0';
  portEXIT_CRITICAL(&g_busyMux);
  return r;
}

const char kPage[] PROGMEM = R"HTML(<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Hologram Cam</title>
<style>body{font-family:system-ui,sans-serif;margin:16px;background:#f6f7f9;color:#1b2230}
button{font:inherit;padding:10px 14px;margin:4px 4px 4px 0;border:0;border-radius:10px;background:#2f6fde;color:#fff}
li{margin:6px 0;list-style:none}a{color:#2f6fde}small{color:#5b6475}.del{background:#c8463b;padding:4px 8px}</style></head>
<body><h2>Hologram Cam</h2>
<p><button onclick="cmd('photo')">Photo</button><button onclick="cmd('record toggle')">Record / stop</button>
<button onclick="cmd('wifi off')">Turn Wi-Fi off</button></p><h3>Media</h3><ul id="files"><li>Loading...</li></ul>
<h3>Firmware update</h3><form method="POST" action="/update" enctype="multipart/form-data">
<input type="file" name="fw" accept=".bin"> <button>Upload</button></form>
<script>
function cmd(c){fetch('/api/cmd?c='+encodeURIComponent(c)).then(load)}
function del(n){if(confirm('Delete '+n+'?'))fetch('/media/'+encodeURIComponent(n),{method:'DELETE'})
.then(r=>{if(!r.ok)r.text().then(alert)}).then(load)}
function el(tag,text){const e=document.createElement(tag);if(text)e.textContent=text;return e}
function load(){fetch('/api/files').then(r=>r.json()).then(fs=>{const ul=document.getElementById('files');
ul.replaceChildren();if(!fs.length)ul.append(el('li','No media yet.'));
fs.sort((a,b)=>a.name<b.name?1:-1).forEach(f=>{const li=el('li'),a=el('a',f.name),b=el('button','x');
a.href='/media/'+encodeURIComponent(f.name);a.download=f.name;b.className='del';b.onclick=()=>del(f.name);
li.append(a,' ',el('small',(f.size/1048576).toFixed(1)+' MB'),' ',b);ul.append(li)})})}
load();setInterval(load,10000);
</script></body></html>)HTML";

bool safeName(const String& n) {
  return n.length() > 0 && n.length() < 40 && n.indexOf('/') < 0 && n.indexOf("..") < 0;
}

void handleFiles() {
  String out = "[";
  File dir = SD.open("/DCIM");
  bool first = true;
  if (dir) {
    for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
      if (f.isDirectory()) continue;
      String name = f.name();
      if (name.startsWith("/")) name = name.substring(name.lastIndexOf('/') + 1);
      out += first ? "" : ",";
      out += "{\"name\":\"" + name + "\",\"size\":" + String(static_cast<unsigned long>(f.size())) + "}";
      first = false;
    }
  }
  out += "]";
  g_server->send(200, "application/json", out);
}

void handleDownload() {
  const String name = g_server->pathArg(0);
  if (!safeName(name)) return g_server->send(400, "text/plain", "bad name");
  if (isBusy(name)) return g_server->send(409, "text/plain", "still recording this file");
  File f = SD.open("/DCIM/" + name);
  if (!f) return g_server->send(404, "text/plain", "not found");
  const char* type = name.endsWith(".jpg") ? "image/jpeg" : "video/x-msvideo";
  g_server->streamFile(f, type);
  f.close();
}

void handleDelete() {
  const String name = g_server->pathArg(0);
  if (!safeName(name)) return g_server->send(400, "text/plain", "bad name");
  if (isBusy(name)) return g_server->send(409, "text/plain", "still recording this file");
  g_server->send(SD.remove("/DCIM/" + name) ? 200 : 404, "text/plain", "ok");
}

void handleCommand() {
  const String c = g_server->arg("c");
  if (g_handler && c.length()) g_handler(c.c_str(), c.length());
  g_server->send(200, "text/plain", "ok");
}

void handleUpdateDone() {
  const Ota result = g_ota;
  g_ota = Ota::Idle;
  if (result == Ota::Refused) return g_server->send(409, "text/plain", "Stop recording first");
  const bool ok = result == Ota::Writing && !Update.hasError();
  g_server->send(ok ? 200 : 500, "text/plain", ok ? "Updated, restarting..." : "Update failed");
  if (!ok) return;
  if (g_handler) g_handler("record stop", 11);   // finish any recording started meanwhile
  vTaskDelay(pdMS_TO_TICKS(1500));
  ESP.restart();
}

void handleUpdateChunk() {
  HTTPUpload& up = g_server->upload();
  switch (up.status) {
    case UPLOAD_FILE_START:
      if (recording()) g_ota = Ota::Refused;                 // never cut a recording short
      else g_ota = Update.begin(UPDATE_SIZE_UNKNOWN) ? Ota::Writing : Ota::Failed;
      break;
    case UPLOAD_FILE_WRITE:
      if (g_ota == Ota::Writing && Update.write(up.buf, up.currentSize) != up.currentSize) g_ota = Ota::Failed;
      break;
    case UPLOAD_FILE_END:
      if (g_ota == Ota::Writing && !Update.end(true)) g_ota = Ota::Failed;
      break;
    case UPLOAD_FILE_ABORTED:
      if (Update.isRunning()) Update.abort();
      g_ota = Ota::Idle;
      break;
  }
  if (g_ota == Ota::Failed && Update.isRunning()) Update.abort();
}

void serve(void*) {
  while (g_serving) {
    g_server->handleClient();
    vTaskDelay(pdMS_TO_TICKS(2));
  }
  xSemaphoreGive(g_taskDone);
  vTaskDelete(nullptr);
}
}  // namespace

void start(CommandHandler onCommand) {
  if (g_active) return;
  g_handler = onCommand;
  static const char kChars[] = "abcdefghjkmnpqrstuvwxyz23456789";
  for (int i = 0; i < 10; ++i) g_pass[i] = kChars[esp_random() % (sizeof(kChars) - 1)];
  g_pass[10] = '\0';
  uint8_t mac[6];
  WiFi.macAddress(mac);
  snprintf(g_ssid, sizeof(g_ssid), "%s%02X%02X", WIFI_SSID_PREFIX, mac[4], mac[5]);
  WiFi.mode(WIFI_AP);
  WiFi.softAP(g_ssid, g_pass);
  snprintf(g_ip, sizeof(g_ip), "%s", WiFi.softAPIP().toString().c_str());

  g_server = new WebServer(80);
  g_server->on("/", HTTP_GET, [] { g_server->send_P(200, "text/html", kPage); });
  g_server->on("/api/files", HTTP_GET, handleFiles);
  g_server->on("/api/cmd", HTTP_GET, handleCommand);
  g_server->on(UriBraces("/media/{}"), HTTP_GET, handleDownload);
  g_server->on(UriBraces("/media/{}"), HTTP_DELETE, handleDelete);
  g_server->on("/update", HTTP_POST, handleUpdateDone, handleUpdateChunk);
  g_server->begin();
  if (!g_taskDone) g_taskDone = xSemaphoreCreateBinary();
  g_serving = true;
  xTaskCreatePinnedToCore(serve, "wifi_sync", 8192, nullptr, 1, &g_task, 0);   // core 0, with the Wi-Fi stack
  g_active = true;
}

void stop() {
  if (!g_active) return;
  g_serving = false;
  WiFi.softAPdisconnect(true);                      // drops clients, so a running download ends quickly
  xSemaphoreTake(g_taskDone, pdMS_TO_TICKS(5000));
  g_task = nullptr;
  g_server->stop();
  delete g_server;
  g_server = nullptr;
  WiFi.mode(WIFI_OFF);
  g_active = false;
  g_ip[0] = '\0';
}

bool active() { return g_active; }

void setBusyFile(const char* path) {
  const char* base = strrchr(path, '/');
  base = base ? base + 1 : path;
  portENTER_CRITICAL(&g_busyMux);
  snprintf(g_busy, sizeof(g_busy), "%s", base);
  portEXIT_CRITICAL(&g_busyMux);
}

const char* ssid() { return g_ssid; }
const char* password() { return g_pass; }
const char* ip() { return g_ip; }

}  // namespace wifi_sync
