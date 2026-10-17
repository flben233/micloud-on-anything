#!/system/bin/sh

if [ "$API" -lt 36 ]; then
  abort "! This module requires Android 16 (API 36). Detected API $API."
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
set_perm "$MODPATH/system.prop" 0 0 0644

ui_print "- Xiaomi Cloud Port installed"
ui_print "- Reboot required"
