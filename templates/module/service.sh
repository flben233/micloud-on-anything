#!/system/bin/sh
MODDIR=${0%/*}
LOG=/data/local/tmp/micloudport.log
exec >>"$LOG" 2>&1
echo "==== service $(date) ===="

for i in $(seq 1 120); do
  [ "$(getprop sys.boot_completed)" = "1" ] && break
  sleep 2
done
# writes (appops/pm grant/install) only work after user 0 is unlocked
for i in $(seq 1 180); do
  [ "$(getprop sys.user.0.ce_available)" = "true" ] && break
  sleep 2
done
sleep 5
wait_service() {
  for i in $(seq 1 90); do
    service check "$1" 2>/dev/null | grep -q found && return 0
    sleep 2
  done
  return 1
}
wait_service package
wait_service settings
wait_service appops
wait_service activity
# live_setup restarts zygote; wait for a stable window before touching appops/pm
sleep 20
OK=0
for i in $(seq 1 120); do
  S=$(settings get global hidden_api_policy 2>&1)
  P=$(pm path com.xiaomi.account 2>&1)
  case "$S" in
    *Failure*) OK=0; sleep 2; continue ;;
  esac
  case "$P" in
    package:*) OK=$((OK + 1)) ;;
    *) OK=0 ;;
  esac
  [ "$OK" -ge 3 ] && break
  sleep 2
done
echo "system ready (ok=$OK)"

if [ "$(getprop ro.debuggable)" = "1" ]; then
  settings put global hidden_api_policy 1
fi

cmd appops set com.miui.cloudservice READ_DEVICE_IDENTIFIERS allow 2>/dev/null
cmd appops set com.xiaomi.simactivate.service READ_DEVICE_IDENTIFIERS allow 2>/dev/null
cmd appops set com.xiaomi.account READ_DEVICE_IDENTIFIERS allow 2>/dev/null
cmd appops set com.miui.cloudbackup READ_DEVICE_IDENTIFIERS allow 2>/dev/null

if [ "$(getprop ro.kernel.qemu)" = "1" ]; then
  settings put global captive_portal_https_url https://connectivitycheck.gstatic.com/generate_204
  settings put global captive_portal_fallback_url https://connectivitycheck.gstatic.com/generate_204
  settings put global captive_portal_other_fallback_urls https://connectivitycheck.gstatic.com/generate_204
  for i in 1 2 3 4 5; do
    [ -e /proc/sys/net/ipv6/conf/wlan0/disable_ipv6 ] && echo 1 > /proc/sys/net/ipv6/conf/wlan0/disable_ipv6 2>/dev/null
    sleep 1
  done
fi

# Sound recorder CTA pre-accept (China compliance gate)
PKG=com.android.soundrecorder
UID=$(dumpsys package "$PKG" 2>/dev/null | grep -m1 'userId=' | sed 's/.*userId=//; s/ .*//')
if [ -n "$UID" ]; then
  PREFS=/data/user/0/$PKG/shared_prefs
  mkdir -p "$PREFS"
  cat > "$PREFS/com.android.soundrecorder_cta.xml" <<'EOF'
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <boolean name="pref_key_support_cta_v2" value="false" />
    <boolean name="pref_key_cta_permissions_accepted" value="true" />
    <boolean name="pref_key_cta_permissions_displayed" value="true" />
    <string name="pref_key_os_version">14574095</string>
</map>
EOF
  chown "$UID:$UID" "$PREFS/com.android.soundrecorder_cta.xml" 2>/dev/null
  chmod 660 "$PREFS/com.android.soundrecorder_cta.xml"
  restorecon "$PREFS/com.android.soundrecorder_cta.xml" 2>/dev/null
  am force-stop "$PKG"
fi

# Cloud ID provider for cloudbackup's device-id path
if ! pm path com.miui.port.cloudid >/dev/null 2>&1; then
  echo "installing CloudIdProvider"
  cp -f "$MODDIR/files/CloudIdProvider.apk" /data/local/tmp/micloudport_cloudid.apk
  chmod 644 /data/local/tmp/micloudport_cloudid.apk
  pm install -r --user 0 /data/local/tmp/micloudport_cloudid.apk
  echo "cloudid install rc=$?"
  rm -f /data/local/tmp/micloudport_cloudid.apk
else
  echo "CloudIdProvider already installed"
fi

# Gallery: install/update the newest Java branch (4.3.1.18-global)
GV=$(dumpsys package com.miui.gallery 2>/dev/null | grep -m1 'versionCode=' | sed 's/.*versionCode=//; s/ .*//')
if [ "$GV" != "4030118" ]; then
  echo "gallery version is '$GV', installing 4.3.1.18-global"
  cp -f "$MODDIR/files/gallery_43118.apk" /data/local/tmp/micloudport_gallery.apk
  chmod 644 /data/local/tmp/micloudport_gallery.apk
  pm install -r -d --user 0 /data/local/tmp/micloudport_gallery.apk
  echo "pm install rc=$?"
  rm -f /data/local/tmp/micloudport_gallery.apk
else
  echo "gallery 4.3.1.18 already installed"
fi

pm grant com.miui.gallery android.permission.READ_MEDIA_IMAGES 2>/dev/null
pm grant com.miui.gallery android.permission.READ_MEDIA_VIDEO 2>/dev/null
pm grant com.miui.gallery android.permission.READ_MEDIA_VISUAL_USER_SELECTED 2>/dev/null
pm grant com.miui.gallery android.permission.ACCESS_MEDIA_LOCATION 2>/dev/null
pm grant com.miui.gallery android.permission.READ_MEDIA_AUDIO 2>/dev/null
pm grant com.miui.gallery android.permission.POST_NOTIFICATIONS 2>/dev/null
cmd appops set com.miui.gallery MANAGE_EXTERNAL_STORAGE allow 2>/dev/null
cmd appops set com.miui.gallery LEGACY_STORAGE allow 2>/dev/null

pm grant com.android.soundrecorder android.permission.RECORD_AUDIO 2>/dev/null
pm grant com.android.soundrecorder android.permission.POST_NOTIFICATIONS 2>/dev/null
pm grant com.android.soundrecorder android.permission.READ_MEDIA_AUDIO 2>/dev/null

for p in android.permission.READ_CONTACTS android.permission.READ_CALL_LOG android.permission.READ_SMS; do
  pm grant com.miui.cloudservice "$p" 2>/dev/null
  pm grant com.miui.micloudsync "$p" 2>/dev/null
  pm grant com.miui.cloudbackup "$p" 2>/dev/null
done
for p in android.permission.READ_MEDIA_IMAGES android.permission.READ_MEDIA_VIDEO android.permission.READ_MEDIA_AUDIO; do
  pm grant com.miui.micloudsync "$p" 2>/dev/null
  pm grant com.miui.cloudbackup "$p" 2>/dev/null
done

"$MODDIR/patch_account_dex.sh"
echo "==== service done ===="
