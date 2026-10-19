#!/system/bin/sh

if [ "$API" -lt 36 ]; then
  abort "! This module requires Android 16 (API 36). Detected API $API."
fi

CALLREC_CONF=/data/adb/micloudport_callrec.conf
CALLREC_CURRENT=$(cat "$CALLREC_CONF" 2>/dev/null)
[ "$CALLREC_CURRENT" = "1" ] || CALLREC_CURRENT=0
if [ "$CALLREC_CURRENT" = "1" ]; then
  ui_print "- Call recording mapping: currently ENABLED"
else
  ui_print "- Call recording mapping: currently disabled"
fi
ui_print "- Map /sdcard/CallRecord to MIUI/sound_recorder/call_rec?"
ui_print "  VOLUME UP = enable, VOLUME DOWN = disable"
ui_print "  No key within 15 seconds = keep current setting"
CALLREC_CHOICE=
rm -f /data/local/tmp/micloudport_keys
if [ -x /system/bin/getevent ]; then
  /system/bin/getevent -l > /data/local/tmp/micloudport_keys 2>/dev/null &
  CALLREC_PID=$!
  CALLREC_I=0
  while [ "$CALLREC_I" -lt 15 ]; do
    if grep -q 'KEY_VOLUMEUP.*DOWN' /data/local/tmp/micloudport_keys 2>/dev/null; then
      CALLREC_CHOICE=1
      break
    fi
    if grep -q 'KEY_VOLUMEDOWN.*DOWN' /data/local/tmp/micloudport_keys 2>/dev/null; then
      CALLREC_CHOICE=0
      break
    fi
    sleep 1
    CALLREC_I=$((CALLREC_I + 1))
  done
  kill "$CALLREC_PID" 2>/dev/null
fi
rm -f /data/local/tmp/micloudport_keys
case "$CALLREC_CHOICE" in
  1) CALLREC_CURRENT=1 ;;
  0) CALLREC_CURRENT=0 ;;
esac
echo "$CALLREC_CURRENT" > "$CALLREC_CONF"
if [ "$CALLREC_CURRENT" = "1" ]; then
  ui_print "- Call recording mapping enabled"
else
  ui_print "- Call recording mapping disabled"
fi

case "$ARCH" in
  arm64)
    mkdir -p "$MODPATH/system/lib64"
    cp -f "$MODPATH/files/libshell_jni_arm64.so" "$MODPATH/system/lib64/libshell_jni.so"
    ;;
  x64|x86_64)
    mkdir -p "$MODPATH/system/lib64"
    cp -f "$MODPATH/files/libshell_jni_x86_64.so" "$MODPATH/system/lib64/libshell_jni.so"
    ;;
  *)
    abort "! Unsupported architecture: $ARCH (need arm64 or x86_64)"
    ;;
esac

ui_print "- Installing $ARCH libshell_jni.so stub"
set_perm_recursive "$MODPATH/system" 0 0 0755 0644
set_perm_recursive "$MODPATH/system/product/app" 0 0 0755 0644
set_perm_recursive "$MODPATH/system/product/priv-app" 0 0 0755 0644
set_perm_recursive "$MODPATH/system/system_ext" 0 0 0755 0644
set_perm_recursive "$MODPATH/system/framework" 0 0 0755 0644
set_perm "$MODPATH/system/lib64/libshell_jni.so" 0 0 0644
set_perm "$MODPATH/post-fs-data.sh" 0 0 0755
set_perm "$MODPATH/service.sh" 0 0 0755
set_perm "$MODPATH/patch_account_dex.sh" 0 0 0755
set_perm "$MODPATH/uninstall.sh" 0 0 0755
set_perm "$MODPATH/system.prop" 0 0 0644

ui_print "- Xiaomi Cloud Port installed"
ui_print "- Reboot required"
