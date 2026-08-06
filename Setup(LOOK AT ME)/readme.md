# TFT_eSPI Setup for CYD Deck

The **TFT_eSPI** library needs a configuration file that tells it which pins your display uses. The ESP32-2432S028 (Cheap Yellow Display) has a specific wiring that isn't the default, so you need to replace one file before compiling.

---

## What to do

Copy **`User_Setup_Select.h`** (the file sitting next to this readme) into your TFT_eSPI library folder, replacing the existing file.

### Default library path

```
C:\Users\YourName\Documents\Arduino\libraries\TFT_eSPI\User_Setup_Select.h
```

Replace `YourName` with your actual Windows username.

> **Tip:** You can find your exact path in Arduino IDE under  
> **File → Preferences → Sketchbook location**  
> Then go into `libraries\TFT_eSPI\` from there.

---

## Step by step

1. Open File Explorer
2. Navigate to:
   ```
   Documents\Arduino\libraries\TFT_eSPI\
   ```
3. Find `User_Setup_Select.h` — this already exists in the folder
4. **Replace it** with the `User_Setup_Select.h` from this folder
5. Re-open Arduino IDE (or just recompile — it will pick up the change)

---

## Why this is needed

TFT_eSPI is a universal display library that supports dozens of different boards. It uses `User_Setup_Select.h` to choose which pin configuration to compile in. The default file points to a generic `User_Setup.h` that doesn't match the CYD's wiring — if you skip this step the display will show nothing or garbage.

The file in this folder has the correct settings for the **ESP32-2432S028** (ILI9341 display, 320×240, with the CYD's specific SPI pins).

---

## After replacing the file

Go back to the main [README](../README.md) and continue with step 5 (flashing the firmware).
