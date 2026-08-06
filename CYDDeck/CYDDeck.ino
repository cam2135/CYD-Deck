/* CYD Deck: ESP32-2432S028 Stream Deck. Configure TFT_eSPI for your CYD before compiling.
   Required libraries: TFT_eSPI, XPT2046_Touchscreen, NimBLE-Arduino,
   ArduinoJson, LittleFS. All persistent deck data is stored in /config.json. */
#include <Arduino.h>
#include <TFT_eSPI.h>
#include <XPT2046_Touchscreen.h>
#include <LittleFS.h>
#include <SD.h>
#include <ArduinoJson.h>
#include <NimBLEDevice.h>
#include <NimBLEHIDDevice.h>

// Common ESP32-2432S028 touch pins; adjust only if your CYD revision differs.
// TFT_eSPI's User_Setup.h already defines TFT_BL. Keep our own name to avoid
// a preprocessor collision when that setup enables the display backlight.
static const uint8_t TOUCH_CS=33, TOUCH_IRQ=36, TOUCH_SCK=25, TOUCH_MISO=39, TOUCH_MOSI=32, BACKLIGHT_PIN=21;
// Built-in CYD TF/microSD slot: CS 5, SCK 18, MISO 19, MOSI 23.
static const uint8_t SD_CARD_CS=5;
static const char *CONFIG="/config.json";
static const char *BLE_NAME="CYD Deck";
TFT_eSPI tft; XPT2046_Touchscreen touch(TOUCH_CS,TOUCH_IRQ); DynamicJsonDocument deck(24576);
NimBLECharacteristic* keyboardInput=nullptr;
// The CYD touch controller has its own SPI pins. Using ESP32's default SPI
// bus here can corrupt TFT transactions and look like static on one side.
SPIClass touchSPI(HSPI);
SPIClass sdSPI(VSPI);
int pageIndex=0, folderDepth=0; String pageStack[8]; bool configDirty=false, sdMounted=false; uint32_t lastTouch=0;

void saveDeck(){ fs::File f=LittleFS.open(CONFIG,"w"); if(!f) return; serializeJson(deck,f); f.close(); configDirty=false; }
void defaultDeck(){ deck.clear(); deck["version"]=1; deck["deviceName"]="CYD Deck"; deck["theme"]="Dark"; deck["brightness"]=180; JsonArray profiles=deck.createNestedArray("profiles"); JsonObject p=profiles.createNestedObject(); p["name"]="Default"; JsonArray pages=p.createNestedArray("pages"); JsonObject home=pages.createNestedObject(); home["name"]="Home"; home.createNestedArray("buttons"); deck["activeProfile"]=0; saveDeck(); }
bool loadDeckFromSD(){ sdSPI.begin(18,19,23,SD_CARD_CS); sdMounted=SD.begin(SD_CARD_CS,sdSPI,10000000); if(!sdMounted) return false; fs::File f=SD.open("/deck.deck",FILE_READ); if(!f) return false; DynamicJsonDocument candidate(24576); DeserializationError err=deserializeJson(candidate,f); f.close(); if(err) return false; deck=candidate; saveDeck(); return true; }
JsonObject currentPage(){ return deck["profiles"][deck["activeProfile"] | 0]["pages"][pageIndex]; }
const uint16_t BG=tft.color565(15,18,24), PANEL=tft.color565(33,39,50), BLUE=tft.color565(27,112,218), ACCENT=tft.color565(43,199,184), TEXT=tft.color565(239,244,250);
uint16_t color(const char* theme){ if(String(theme)=="OLED Black") return TFT_BLACK; if(String(theme)=="Blue") return tft.color565(16,45,86); if(String(theme)=="Purple") return tft.color565(58,32,90); if(String(theme)=="Green") return tft.color565(18,75,61); return PANEL; }
void title(const String&s){ tft.setTextDatum(TL_DATUM); tft.setTextColor(TEXT,BG); tft.setTextSize(2); tft.drawString(s,8,5); }
void drawHomeButton(){ if(folderDepth<=0)return; uint16_t bg=tft.color565(60,80,50); tft.fillRoundRect(260,2,56,24,6,bg); tft.drawRoundRect(260,2,56,24,6,ACCENT); tft.setTextDatum(MC_DATUM); tft.setTextColor(TEXT,bg); tft.setTextSize(1); tft.drawString("Home",288,14); }
// Returns true if the touch hit the home button and it was handled.
// Jumps all the way back to page index 0 (the root home page) regardless
// of how many folder levels deep you are — one tap always goes fully home.
bool touchHomeButton(int x, int y) {
  if (folderDepth <= 0) return false;
  if (x >= 260 && x <= 316 && y >= 2 && y <= 26) {
    folderDepth = 0;   // clear the whole stack — go fully home
    pageIndex = 0;
    drawDeck();
    return true;
  }
  return false;
}
void drawButton(int slot, const char* name, const char* type, bool active=false){ int col=slot%4,row=slot/4,x=4+col*79,y=31+row*103; uint16_t bg=active?BLUE:color(deck["theme"]|"Dark"); tft.fillRoundRect(x,y,72,94,10,bg); tft.drawRoundRect(x,y,72,94,10,active?ACCENT:BLUE); tft.setTextDatum(MC_DATUM); tft.setTextColor(TEXT,bg); tft.setTextSize(3); tft.drawString(String(type)=="Folder"?"+":"*",x+36,y+27); tft.setTextSize(1); String n=name; if(n.length()>12)n=n.substring(0,11)+"."; tft.drawString(n,x+36,y+69); }
void drawDeck(){ tft.fillScreen(BG); JsonObject p=currentPage(); title(String(deck["deviceName"]|BLE_NAME)+" - "+String(p["name"]|"Home")); drawHomeButton(); JsonArray b=p["buttons"].as<JsonArray>();
 for(int i=0;i<8;i++){ if(i<b.size()) drawButton(i,b[i]["name"]|"Button",b[i]["type"]|"Custom"); }
}
// HID keyboard helpers. Windows receives a normal physical-keyboard sequence.
// BLE HID reports need a small gap on some Windows Bluetooth adapters.  Sending
// them too quickly can lose characters, especially immediately after Win+R.
void sendKey(uint8_t modifier,uint8_t key){ if(!keyboardInput)return; uint8_t report[8]={modifier,0,key,0,0,0,0,0}; keyboardInput->setValue(report,sizeof(report)); keyboardInput->notify(); delay(10); uint8_t released[8]={0}; keyboardInput->setValue(released,sizeof(released)); keyboardInput->notify(); delay(20); }
void typeText(const String& text){
  for(size_t i=0;i<text.length();i++){
    char c=text[i]; uint8_t mod=0,key=0;
    if(c>='a'&&c<='z') key=0x04 + c - 'a';
    else if(c>='A'&&c<='Z'){ key=0x04 + c - 'A'; mod=0x02; }
    else if(c>='1'&&c<='9') key=0x1E + c - '1';
    else if(c=='0') key=0x27;
    else {
      switch(c){
        case ' ': key=0x2C; break;
        case '.': key=0x37; break;
        case '\\':key=0x31; break;
        case '/': key=0x38; break;
        case '-': key=0x2D; break;
        case '_': key=0x2D; mod=0x02; break;
        case ':': key=0x33; mod=0x02; break;
        case ';': key=0x33; break;
        case '(': key=0x26; mod=0x02; break;
        case ')': key=0x27; mod=0x02; break;
        // URL and general punctuation
        case '?': key=0x38; mod=0x02; break;
        case '&': key=0x24; mod=0x02; break;
        case '=': key=0x2E; break;
        case '#': key=0x20; mod=0x02; break;
        case '%': key=0x22; mod=0x02; break;
        case '+': key=0x2E; mod=0x02; break;
        case '@': key=0x1F; mod=0x02; break;
        case ',': key=0x36; break;
        case '\'':key=0x34; break;
        case '"': key=0x34; mod=0x02; break;
        case '!': key=0x1E; mod=0x02; break;
        case '~': key=0x35; mod=0x02; break;
        case '`': key=0x35; break;
        case '[': key=0x2F; break;
        case ']': key=0x30; break;
        case '{': key=0x2F; mod=0x02; break;
        case '}': key=0x30; mod=0x02; break;
        case '<': key=0x36; mod=0x02; break;
        case '>': key=0x37; mod=0x02; break;
        case '|': key=0x31; mod=0x02; break;
        case '*': key=0x25; mod=0x02; break;
        case '^': key=0x23; mod=0x02; break;
        case '$': key=0x21; mod=0x02; break;
        default: Serial.print("typeText: skipped char 0x"); Serial.println((uint8_t)c,HEX); continue;
      }
    }
    sendKey(mod,key);
  }
}
void openOnWindows(const String& target){
  if(target.length()==0)return;
  sendKey(0x08,0x15);             // Win + R
  delay(350);                     // wait until the Windows Run field accepts input
  typeText(target);               // HID keyboards cannot set the host clipboard; type reliably instead
  delay(80);
  sendKey(0,0x28);                // Enter
}

// Parse a shortcut string like "Ctrl+Shift+C" into a modifier byte + keycode and send it.
// Supported modifiers: Ctrl, Shift, Alt, Win (case-insensitive). Key must be last token.
void sendShortcut(const String& shortcut) {
  uint8_t mod=0; String s=shortcut; s.trim();
  // Walk tokens separated by '+', collect modifiers, last token is the key.
  String tokens[8]; uint8_t count=0;
  int start=0;
  for(int i=0;i<=s.length();i++){
    if(i==s.length()||s[i]=='+'){
      String tok=s.substring(start,i); tok.trim();
      if(count<8) tokens[count++]=tok;
      start=i+1;
    }
  }
  if(count==0) return;
  // All tokens except the last are modifiers.
  for(uint8_t i=0;i<count-1;i++){
    String m=tokens[i]; m.toLowerCase();
    if(m=="ctrl"||m=="control") mod|=0x01;
    else if(m=="shift")         mod|=0x02;
    else if(m=="alt")           mod|=0x04;
    else if(m=="win"||m=="gui") mod|=0x08;
  }
  // Last token is the key.
  String k=tokens[count-1]; k.trim();
  uint8_t key=0;
  if(k.length()==1){
    char c=k[0];
    if(c>='a'&&c<='z')      key=0x04 + c - 'a';
    else if(c>='A'&&c<='Z') key=0x04 + c - 'A';
    else if(c>='1'&&c<='9') key=0x1E + c - '1';
    else if(c=='0')          key=0x27;
    else {
      // Single punctuation — reuse typeText logic via a one-char string
      typeText(k); return;
    }
  } else {
    // Named keys
    String kl=k; kl.toLowerCase();
    if(kl=="f1")  key=0x3A; else if(kl=="f2")  key=0x3B; else if(kl=="f3")  key=0x3C;
    else if(kl=="f4")  key=0x3D; else if(kl=="f5")  key=0x3E; else if(kl=="f6")  key=0x3F;
    else if(kl=="f7")  key=0x40; else if(kl=="f8")  key=0x41; else if(kl=="f9")  key=0x42;
    else if(kl=="f10") key=0x43; else if(kl=="f11") key=0x44; else if(kl=="f12") key=0x45;
    else if(kl=="enter"||kl=="return") key=0x28;
    else if(kl=="esc"||kl=="escape")   key=0x29;
    else if(kl=="tab")    key=0x2B;
    else if(kl=="space")  key=0x2C;
    else if(kl=="del"||kl=="delete")   key=0x4C;
    else if(kl=="backspace")           key=0x2A;
    else if(kl=="up")     key=0x52; else if(kl=="down")  key=0x51;
    else if(kl=="left")   key=0x50; else if(kl=="right") key=0x4F;
    else if(kl=="home")   key=0x4A; else if(kl=="end")   key=0x4D;
    else if(kl=="pgup")   key=0x4B; else if(kl=="pgdn")  key=0x4E;
    else if(kl=="print"||kl=="prtsc")  key=0x46;
    else { Serial.print("sendShortcut: unknown key: "); Serial.println(k); return; }
  }
  sendKey(mod, key);
}

void executeButton(JsonObject b) {
  String type=b["type"]|"", action=b["action"]|"";
  if(type=="Folder"){
    String target=b["folder"]|"";
    JsonArray pages=deck["profiles"][deck["activeProfile"]|0]["pages"];
    for(uint8_t i=0;i<pages.size();i++){
      if(target==String(pages[i]["name"]|"")){
        // Bounds-check before pushing onto the stack.
        if(folderDepth<8) pageStack[folderDepth++]=String(currentPage()["name"]|"");
        pageIndex=i; drawDeck(); return;
      }
    }
  }
  if(type=="Keyboard Shortcut"){ sendShortcut(action); }
  else if(type=="Application"||type=="Open File"||type=="Open Folder"||type=="Website"){ openOnWindows(action); }
  else if(type!="Folder"){ Serial.print("executeButton: unhandled type: "); Serial.println(type); }
  if(b["toggle"]|false){
    bool state=b["state"]|false; b["state"]=!state;
    configDirty=true; // persist the toggled state across reboots
  }
  drawDeck();
}
void handleTouch(){ if(!touch.touched()||millis()-lastTouch<180)return; TS_Point p=touch.getPoint(); lastTouch=millis(); int x=map(p.x,200,3700,0,320),y=map(p.y,240,3800,0,240); if(x<0||x>320||y<0)return; if(touchHomeButton(x,y))return; if(y<31)return; int col=x/80,row=(y-31)/103; if(col>3||row>1)return; int n=row*4+col; JsonArray b=currentPage()["buttons"].as<JsonArray>(); if(n<b.size()) executeButton(b[n]); }

void welcome(){ tft.fillScreen(TFT_BLACK); tft.setTextDatum(MC_DATUM); tft.setTextColor(TFT_YELLOW,TFT_BLACK); tft.setTextSize(2); tft.drawString("Welcome to CYD Deck",160,90); tft.setTextSize(1); tft.drawString("Insert SD card with deck.deck",160,125); delay(1500); }
// Standard boot-keyboard report. Windows therefore lists this as one keyboard,
// called "CYD Deck", rather than a generic/unknown BLE peripheral.
static uint8_t keyboardReportMap[] = {
  0x05,0x01,0x09,0x06,0xA1,0x01,0x85,0x01,0x05,0x07,0x19,0xE0,0x29,0xE7,
  0x15,0x00,0x25,0x01,0x75,0x01,0x95,0x08,0x81,0x02,0x95,0x01,0x75,0x08,
  0x81,0x01,0x95,0x05,0x75,0x01,0x05,0x08,0x19,0x01,0x29,0x05,0x91,0x02,
  0x95,0x01,0x75,0x03,0x91,0x01,0x95,0x06,0x75,0x08,0x15,0x00,0x25,0x65,
  0x05,0x07,0x19,0x00,0x29,0x65,0x81,0x00,0xC0
};
void startBLE(){
  NimBLEDevice::init(BLE_NAME);
  NimBLEDevice::setDeviceName(BLE_NAME);
  // Give this physical CYD one deterministic static address derived from its
  // eFuse MAC. This stops Windows creating a new Unknown device per reboot.
  uint64_t chipMac=ESP.getEfuseMac(); uint8_t bleAddress[6];
  for(uint8_t i=0;i<6;i++) bleAddress[i]=(chipMac>>(8*i))&0xFF;
  bleAddress[5]=(bleAddress[5]&0x3F)|0xC0; // Bluetooth static-random address bits.
  NimBLEDevice::setOwnAddrType(BLE_OWN_ADDR_RANDOM);
  NimBLEDevice::setOwnAddr(bleAddress);
  // Bonded Just Works pairing: Windows remembers the keyboard and reconnects
  // after reboot, but MITM is off so it never asks for a PIN/passcode.
  NimBLEDevice::setSecurityIOCap(0x03); // BLE_HS_IO_NO_INPUT_OUTPUT: no PIN prompt is possible.
  NimBLEDevice::setSecurityAuth(true,false,true);
  NimBLEServer* server=NimBLEDevice::createServer();
  server->advertiseOnDisconnect(true);
  NimBLEHIDDevice* hid=new NimBLEHIDDevice(server);
  keyboardInput=hid->getInputReport(1); hid->setManufacturer(BLE_NAME); hid->setPnp(0x02,0xE502,0x0001,0x0100);
  hid->setHidInfo(0x00,0x01); hid->setReportMap(keyboardReportMap,sizeof(keyboardReportMap));
  server->start();
  NimBLEAdvertising* advertising=NimBLEDevice::getAdvertising();
  advertising->setAppearance(HID_KEYBOARD);
  advertising->setName(BLE_NAME);               // Name is in the advertisement, not only the GATT database.
  advertising->enableScanResponse(true);
  advertising->addServiceUUID(hid->getHidService()->getUUID());
  advertising->start();
}
void setup(){ Serial.begin(115200); pinMode(BACKLIGHT_PIN,OUTPUT); digitalWrite(BACKLIGHT_PIN,HIGH); tft.init(); tft.setRotation(1); tft.invertDisplay(false); touchSPI.begin(TOUCH_SCK,TOUCH_MISO,TOUCH_MOSI,TOUCH_CS); touch.begin(touchSPI); touch.setRotation(1); if(!LittleFS.begin(true)) { tft.println("LittleFS failed"); return; } fs::File f=LittleFS.open(CONFIG,"r"); if(f){ if(deserializeJson(deck,f)!=DeserializationError::Ok)defaultDeck(); f.close(); } else { defaultDeck(); welcome(); } loadDeckFromSD();
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(BACKLIGHT_PIN,5000,8); ledcWrite(BACKLIGHT_PIN,deck["brightness"]|180);
#else
  ledcSetup(0,5000,8); ledcAttachPin(BACKLIGHT_PIN,0); ledcWrite(0,deck["brightness"]|180);
#endif
  startBLE(); drawDeck(); }
void loop(){ handleTouch(); if(configDirty)saveDeck(); delay(8); }
