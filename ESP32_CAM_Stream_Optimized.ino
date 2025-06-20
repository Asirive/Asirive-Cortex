#define CAMERA_MODEL_AI_THINKER // Has PSRAM

#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include "soc/soc.h"           // Disable brownout problems
#include "soc/rtc_cntl_reg.h"  // Disable brownout problems
#include "driver/i2s.h"

// Replace with your network credentials
const char* ssid = "Epicwifi";
const char* password = "Epicwifi";

WebServer server(80);

// MJPEG streaming boundary
#define PART_BOUNDARY "123456789000000000000987654321"
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

// Streaming configuration
#define STREAM_CHUNK_SIZE 5120 // Send data in 1KB chunks
#define STREAM_DELAY_MS 10   // Attempt to stream as fast as possible - Reverted to 10 for stability

// Camera configuration for AI Thinker ESP32-CAM
camera_config_t config;

void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0); //disable brownout detector
  
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();
  Serial.println("Starting ESP32-CAM Optimized Stream...");

  // Camera configuration
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = 5;
  config.pin_d1 = 18;
  config.pin_d2 = 19;
  config.pin_d3 = 21;
  config.pin_d4 = 36;
  config.pin_d5 = 39;
  config.pin_d6 = 34;
  config.pin_d7 = 35;
  config.pin_xclk = 0;
  config.pin_pclk = 22;
  config.pin_vsync = 25;
  config.pin_href = 23;
  config.pin_sscb_sda = 26;
  config.pin_sscb_scl = 27;
  config.pin_pwdn = 32;
  config.pin_reset = -1;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  
  // Optimized frame size and quality settings for better streaming
  if(psramFound()){
    config.frame_size = FRAMESIZE_CIF;    // 352x288 - smaller for better streaming
    config.jpeg_quality = 30;             // Lower quality for smaller file size (~<30KB)
    config.fb_count = 2;
    Serial.println("PSRAM found - using CIF resolution for streaming");
  } else {
    config.frame_size = FRAMESIZE_QVGA;   // 320x240 - very small
    config.jpeg_quality = 35;             // Lower quality for smaller file size
    config.fb_count = 1;
    Serial.println("No PSRAM - using QVGA resolution");
  }

  // Camera init
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x\n", err);
    return;
  }
  Serial.println("Camera initialized successfully");

  // Camera sensor adjustments for better streaming
  sensor_t * s = esp_camera_sensor_get();
  if (s->id.PID == OV3660_PID) {
    s->set_vflip(s, 1);        // flip it back
    s->set_brightness(s, 1);   // up the brightness just a bit
    s->set_saturation(s, -2);  // lower the saturation
  }
  
  // The following lines that unconditionally set parameters are commented out
  // to allow settings from esp_camera_init (based on PSRAM) to take precedence
  // and to preserve sensor-specific brightness adjustments.
  // s->set_framesize(s, FRAMESIZE_CIF);    // Using frame size from esp_camera_init
  // s->set_quality(s, 15);                 // Using JPEG quality from esp_camera_init
  // s->set_brightness(s, 0);               // Using brightness from sensor-specific or esp_camera_init
  
  s->set_contrast(s, 0);                 // Normal contrast (this is likely fine)

  // Connect to Wi-Fi
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  
  int wifi_timeout = 0;
  while (WiFi.status() != WL_CONNECTED && wifi_timeout < 20) {
    delay(500);
    Serial.print(".");
    wifi_timeout++;
  }
  
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nWiFi connection failed!");
    return;
  }
  
  Serial.println("");
  Serial.println("WiFi connected successfully");
  Serial.print("Camera Stream Ready! Go to: http://");
  Serial.print(WiFi.localIP());
  Serial.println("/stream");
  Serial.print("Web interface: http://");
  Serial.print(WiFi.localIP());
  Serial.println("/");

  // Setup web server routes
  server.on("/", handleRoot);
  server.on("/stream", handleStream);
  server.on("/capture", handleCapture);
  server.on("/test", handleTest);
  server.onNotFound(handleNotFound);

  // Start server
  server.begin();
  Serial.println("HTTP server started with optimized streaming");
}

void loop() {
  server.handleClient();
  delay(1);
}

// Handle root page with live stream preview
void handleRoot() {
  String html = "<!DOCTYPE html><html>";
  html += "<head><title>ESP32-CAM Optimized Stream</title>";
  html += "<meta name='viewport' content='width=device-width, initial-scale=1'>";
  html += "<style>body{font-family:Arial;margin:0;text-align:center;background:#f0f0f0;}";
  html += "h1{color:#333;margin-top:20px;}";
  html += "img{max-width:100%;height:auto;border:2px solid #333;margin:20px;}";
  html += "a{display:inline-block;margin:10px;padding:10px 20px;background:#007bff;color:white;text-decoration:none;border-radius:5px;}";
  html += "a:hover{background:#0056b3;}";
  html += ".info{background:#e9ecef;padding:15px;margin:20px;border-radius:5px;text-align:left;}";
  html += "</style></head>";
  html += "<body><h1>ESP32-CAM Optimized Stream</h1>";
  html += "<div class='info'>";
  html += "<strong>Stream Info:</strong><br>";
  html += "Resolution: 352x288 (CIF)<br>";
  html += "Quality: Moderate (smaller file size)<br>";
  html += "Frame Rate: ~10 FPS<br>";
  html += "Chunked Transfer: Enabled";
  html += "</div>";
  html += "<img src='/stream' id='stream'>";
  html += "<br><a href='/capture'>Capture Single Frame</a>";
  html += "<a href='/test'>Test Connection</a>";
  html += "<p>Stream URL: <code>http://" + WiFi.localIP().toString() + "/stream</code></p>";
  html += "<script>";
  html += "var retryCount = 0;";
  html += "document.getElementById('stream').onerror = function() {";
  html += "  retryCount++;";
  html += "  if (retryCount < 3) {";
  html += "    setTimeout(() => { this.src = '/stream?t=' + Date.now(); }, 2000);";
  html += "  } else {";
  html += "    this.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMzUyIiBoZWlnaHQ9IjI4OCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMTAwJSIgaGVpZ2h0PSIxMDAlIiBmaWxsPSIjY2NjIi8+PHRleHQgeD0iNTAlIiB5PSI1MCUiIGZvcnQtZmFtaWx5PSJBcmlhbCwgc2Fucy1zZXJpZiIgZm9udC1zaXplPSIxNiIgZmlsbD0iIzMzMyIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZHk9Ii4zZW0iPkNhbWVyYSBTdHJlYW0gRmFpbGVkPC90ZXh0Pjwvc3ZnPg==';";
  html += "  }";
  html += "};";
  html += "</script></body></html>";
  
  server.send(200, "text/html", html);
}

// Optimized MJPEG stream handler with chunked transfer
void handleStream() {
  Serial.println("Stream requested - using optimized chunked transfer");
  
  WiFiClient client = server.client();
  
  if (!client) {
    Serial.println("No client connected");
    return;
  }
  
  // Send HTTP headers with chunked transfer encoding
  client.println("HTTP/1.1 200 OK");
  client.printf("Content-Type: %s\r\n", _STREAM_CONTENT_TYPE); // Corrected CRLF sequence
  client.println("Connection: keep-alive"); // Changed from close to keep-alive
  client.println("Access-Control-Allow-Origin: *");
  client.println("X-Framerate: 10"); 
  client.println();
  
  Serial.println("Starting optimized MJPEG stream");
  
  unsigned long lastFrame = 0;
  int frameCount = 0;
  
  while (client.connected()) {
    // Control frame rate
    if (millis() - lastFrame < STREAM_DELAY_MS) { // With STREAM_DELAY_MS = 0, this block is unlikely to be entered
      delay(10); // This delay is effectively bypassed
      continue;
    }
    lastFrame = millis();
    
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("Camera capture failed");
      break;
    }
    
    Serial.printf("Frame %d: %d bytes\\n", frameCount++, fb->len);
    
    // Send MJPEG boundary
    if (!sendChunked(client, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY))) {
      Serial.println("Failed to send boundary");
      esp_camera_fb_return(fb);
      break;
    }
    
    // Send frame headers
    char part_buf[64];
    size_t hlen = snprintf(part_buf, 64, _STREAM_PART, fb->len);
    if (!sendChunked(client, part_buf, hlen)) {
      Serial.println("Failed to send headers");
      esp_camera_fb_return(fb);
      break;
    }
    
    // Send the actual image data in chunks
    if (!sendImageChunked(client, fb->buf, fb->len)) {
      Serial.println("Failed to send image data");
      esp_camera_fb_return(fb);
      break;
    }
    
    esp_camera_fb_return(fb);
    
    // Check client connection
    if (!client.connected()) {
      Serial.println("Client disconnected");
      break;
    }
    
    // Small delay to prevent overwhelming the network and allow other tasks
    delay(10); // Reverted to 10ms for stability
  }
  
  Serial.println("Stream ended");
}

// Send data in chunks with error checking
bool sendChunked(WiFiClient &client, const char* data, size_t len) {
  size_t sent = 0;
  while (sent < len && client.connected()) {
    size_t chunkSize = min((size_t)STREAM_CHUNK_SIZE, len - sent);
    size_t written = client.write((const uint8_t*)(data + sent), chunkSize);
    
    if (written == 0) {
      // Client buffer full, wait a bit
      delay(20); // Increased from 10 to 20
      continue;
    }
    
    sent += written;
    
    // Small delay between chunks
    if (chunkSize == STREAM_CHUNK_SIZE) {
      delay(5); // Increased from 1 to 5
    }
  }
  
  return sent == len;
}

// Send image data in chunks with progress tracking
bool sendImageChunked(WiFiClient &client, const uint8_t* data, size_t len) {
  size_t sent = 0;
  size_t totalChunks = (len + STREAM_CHUNK_SIZE - 1) / STREAM_CHUNK_SIZE;
  size_t currentChunk = 0;
  
  while (sent < len && client.connected()) {
    size_t chunkSize = min((size_t)STREAM_CHUNK_SIZE, len - sent);
    size_t written = client.write(data + sent, chunkSize);
    
    if (written == 0) {
      // Client buffer full, wait
      delay(30); // Increased from 20 to 30
      continue;
    }
    
    sent += written;
    currentChunk++;
    
    // Progress logging for debugging
    if (currentChunk % 5 == 0 || currentChunk == totalChunks) {
      Serial.printf("Sent chunk %d/%d (%d/%d bytes)\n", currentChunk, totalChunks, sent, len);
    }
    
    // Adaptive delay based on chunk size
    if (written == chunkSize && chunkSize == STREAM_CHUNK_SIZE) {
      delay(5); // Increased from 2 to 5
    }
  }
  
  bool success = (sent == len);
  if (!success) {
    Serial.printf("Image send incomplete: %d/%d bytes\n", sent, len);
  }
  
  return success;
}

// Handle single image capture with better error handling
void handleCapture() {
  Serial.println("Single capture requested");
  
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Camera capture failed");
    server.send(500, "text/plain", "Camera capture failed");
    return;
  }
  
  Serial.printf("Captured image: %d bytes\n", fb->len);
  
  server.sendHeader("Content-Disposition", "inline; filename=capture.jpg");
  server.sendHeader("Cache-Control", "no-cache");
  
  // Send image in chunks for large captures too
  server.setContentLength(fb->len);
  server.send(200, "image/jpeg", "");
  
  WiFiClient client = server.client();
  if (!sendImageChunked(client, fb->buf, fb->len)) {
    Serial.println("Failed to send captured image");
  }
  
  esp_camera_fb_return(fb);
}

// Test endpoint for connectivity checking
void handleTest() {
  String response = "ESP32-CAM Test Response\n";
  response += "Time: " + String(millis()) + "ms\n";
  response += "Free heap: " + String(ESP.getFreeHeap()) + " bytes\n";
  response += "WiFi RSSI: " + String(WiFi.RSSI()) + " dBm\n";
  response += "Camera status: " + String(esp_camera_sensor_get() ? "OK" : "FAIL") + "\n";
  
  server.send(200, "text/plain", response);
}

// Handle 404
void handleNotFound() {
  String message = "File Not Found\n\n";
  message += "URI: ";
  message += server.uri();
  message += "\nMethod: ";
  message += (server.method() == HTTP_GET) ? "GET" : "POST";
  message += "\nArguments: ";
  message += server.args();
  message += "\n";
  
  for (uint8_t i = 0; i < server.args(); i++) {
    message += " " + server.argName(i) + ": " + server.arg(i) + "\n";
  }
  
  server.send(404, "text/plain", message);
}

// ===================
// I2S Microphone Pins
// ===================
#define I2S_WS 13
#define I2S_SD 12
#define I2S_SCK 14
#define I2S_PORT I2S_NUM_0

#define I2S_SAMPLE_RATE 16000
#define I2S_READ_LEN    (4 * 1024)
// ===================
