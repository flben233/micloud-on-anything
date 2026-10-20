#!/system/bin/sh
MODDIR=${0%/*}
LOG=/data/local/tmp/micloudport.log
exec >>"$LOG" 2>&1
echo "==== post-fs-data $(date) ===="

RESETPROP=/data/adb/magisk/resetprop
[ -x "$RESETPROP" ] || RESETPROP=resetprop

set_prop() {
  "$RESETPROP" -n "$1" "$2" 2>/dev/null || setprop "$1" "$2" 2>/dev/null
}

set_prop ro.miui.ui.version.code 816
set_prop ro.miui.ui.version.name V816
set_prop ro.mi.os.version.code 3
set_prop ro.mi.os.version.name OS3.0
set_prop ro.mi.os.version.incremental OS3.0.312.0.WPACNXM
set_prop ro.mi.os.version.publish true
set_prop ro.mi.os.version.beta false
set_prop ro.miui.build.region cn
set_prop ro.product.mod_device nezha
set_prop ro.miui.notch 1
set_prop ro.miui.restrict_imei 1
set_prop ro.miui.ui.font.animation disable
set_prop ro.ai.os.version.code 4
set_prop ro.ai.os.version.name OS3.1
set_prop ro.miui.region CN
set_prop persist.sys.computility.version 2025
set_prop persist.sys.computility.cpulevel 5
set_prop persist.sys.computility.gpulevel 5

MODVER=$(grep '^versionCode=' "$MODDIR/module.prop" | cut -d= -f2)
CACHEVER=$(cat /data/adb/micloudport_cache_ver 2>/dev/null)
if [ "$MODVER" != "$CACHEVER" ]; then
  echo "clearing package_cache (module $MODVER, previous $CACHEVER)"
  rm -rf /data/system/package_cache/*
  echo "$MODVER" > /data/adb/micloudport_cache_ver
fi

echo "==== post-fs-data done ===="
