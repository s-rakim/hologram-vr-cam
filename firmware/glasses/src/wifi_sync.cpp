#include "wifi_sync.h"

#include <SD.h>
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
bool g_active = false;
char g_ssid[32] = {0};
char g_pass[16] = {0};
char g_ip[16] = {0};

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
function del(n){if(confirm('Delete '+n+'?'))fetch('/media/'+n,{method:'DELETE'}).then(load)}
function load(){fetch('/api/files').then(r=>r.json()).then(fs=>{const ul=document.getElementById('files');
ul.innerHTML=fs.length?'':'<li>No media yet.</li>';fs.sort((a,b)=>a.name<b.name?1:-1).forEach(f=>{const li=document.createElement('li');
li.innerHTML='<a href="/media/'+f.name+'" download>'+f.name+'</a> <small>'+(f.size/1048576).toFixed(1)+' MB</small> '+
'<button class="del" onclick="del(\''+f.name+'\')">x</button>';ul.appendChild(li)})})}
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
  File f = SD.open("/DCIM/" + name);
  if (!f) return g_server->send(404, "text/plain", "not found");
  const char* type = name.endsWith(".jpg") ? "image/jpeg" : "video/x-msvideo";
  g_server->streamFile(f, type);
  f.close();
}

void handleDelete() {
  const String name = g_server->pathArg(0);
  if (!safeName(name)) return g_server->send(400, "text/plain", "bad name");
  g_server->send(SD.remove("/DCIM/" + name) ? 200 : 404, "text/plain", "ok");
}

void handleCommand() {
  const String c = g_server->arg("c");
  if (g_handler && c.length()) g_handler(c.c_str(), c.length());
  g_server->send(200, "text/plain", "ok");
}

void handleUpdateDone() {
  const bool ok = !Update.hasError();
  g_server->send(200, "text/plain", ok ? "Updated, restarting..." : "Update failed");
  if (ok) {
    delay(500);
    ESP.restart();
  }
}

void handleUpdateChunk() {
  HTTPUpload& up = g_server->upload();
  if (up.status == UPLOAD_FILE_START) Update.begin(UPDATE_SIZE_UNKNOWN);
  else if (up.status == UPLOAD_FILE_WRITE) Update.write(up.buf, up.currentSize);
  else if (up.status == UPLOAD_FILE_END) Update.end(true);
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
  g_active = true;
}

void stop() {
  if (!g_active) return;
  g_server->stop();
  delete g_server;
  g_server = nullptr;
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_OFF);
  g_active = false;
  g_ip[0] = '\0';
}

bool active() { return g_active; }

void loop() {
  if (g_server) g_server->handleClient();
}

const char* ssid() { return g_ssid; }
const char* password() { return g_pass; }
const char* ip() { return g_ip; }

}  // namespace wifi_sync
