#!/system/bin/sh

LOG=/data/local/tmp/micloudport-uninstall.log
exec >>"$LOG" 2>&1
echo "==== uninstall $(date) ===="

am force-stop com.xiaomi.account 2>/dev/null
umount -l /product/app/MIUIXiaomiAccount/MIUIXiaomiAccount.apk 2>/dev/null

for ISA in x86_64 arm64; do
  D=/data/dalvik-cache/$ISA
  NAME='product@app@MIUIXiaomiAccount@MIUIXiaomiAccount.apk@classes'
  rm -f "$D/$NAME.dex" "$D/$NAME.vdex"
done

rm -f /data/adb/micloudport_acct_*.done
rm -f /data/adb/micloudport_cache_ver
rm -rf /data/local/tmp/micloudport_acct
rm -f /data/local/tmp/micloudport.log
rm -f /data/local/tmp/micloudport_cloudid.apk
rm -f /data/local/tmp/micloudport_gallery.apk
rm -rf /data/adb/modules_update/micloudport

if pm path com.miui.port.cloudid >/dev/null 2>&1; then
  pm uninstall --user 0 com.miui.port.cloudid
fi
rm -rf /data/user/0/com.miui.port.cloudid

GALLERY_PATH=$(pm path com.miui.gallery 2>/dev/null | head -n 1)
GALLERY_VERSION=$(dumpsys package com.miui.gallery 2>/dev/null | grep -m1 'versionCode=' | sed 's/.*versionCode=//; s/ .*//')
case "$GALLERY_PATH" in
  package:/data/app/*)
    if [ "$GALLERY_VERSION" = "4030118" ]; then
      pm uninstall --user 0 com.miui.gallery
    fi
    ;;
esac

for PKG in com.miui.cloudservice com.xiaomi.simactivate.service com.xiaomi.account com.miui.cloudbackup; do
  cmd appops set "$PKG" READ_DEVICE_IDENTIFIERS default 2>/dev/null
done
cmd appops set com.miui.gallery MANAGE_EXTERNAL_STORAGE default 2>/dev/null
cmd appops set com.miui.gallery LEGACY_STORAGE default 2>/dev/null

settings delete global hidden_api_policy 2>/dev/null
if [ "$(getprop ro.kernel.qemu)" = "1" ]; then
  settings delete global captive_portal_https_url 2>/dev/null
  settings delete global captive_portal_fallback_url 2>/dev/null
  settings delete global captive_portal_other_fallback_urls 2>/dev/null
fi

rm -f /data/user/0/com.android.soundrecorder/shared_prefs/com.android.soundrecorder_cta.xml
sync
echo "==== uninstall done ===="
