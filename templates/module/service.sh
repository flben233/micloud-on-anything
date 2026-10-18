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
pm grant com.xiaomi.simactivate.service android.permission.READ_PHONE_STATE 2>/dev/null
pm grant com.miui.cloudservice android.permission.READ_PHONE_STATE 2>/dev/null


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
CLOUDID_APK="$MODDIR/system/product/app/CloudIdProvider/CloudIdProvider.apk"
if ! pm path com.miui.port.cloudid >/dev/null 2>&1; then
  echo "installing CloudIdProvider"
  cp -f "$CLOUDID_APK" /data/local/tmp/micloudport_cloudid.apk
  chmod 644 /data/local/tmp/micloudport_cloudid.apk
  pm install -r --user 0 /data/local/tmp/micloudport_cloudid.apk
  echo "cloudid install rc=$?"
  rm -f /data/local/tmp/micloudport_cloudid.apk
else
  echo "CloudIdProvider already installed: $(pm path com.miui.port.cloudid)"
fi

# Xposed module: install/update the libxposed APK and configure Vector scope
XPACKAGE=com.miui.port.xposed
XV=$(dumpsys package "$XPACKAGE" 2>/dev/null | grep -m1 'versionCode=' | sed 's/.*versionCode=//; s/ .*//')
INSTALL_XPOSED=0
if [ -z "$XV" ]; then
  INSTALL_XPOSED=1
elif [ "$XV" -lt 2 ] 2>/dev/null; then
  INSTALL_XPOSED=1
fi
XPOSED_APK="$MODDIR/system/product/app/MiCloudXposed/MiCloudXposed.apk"
if [ "$INSTALL_XPOSED" = "1" ]; then
  echo "installing MiCloudXposed ($XV)"
  cp -f "$XPOSED_APK" /data/local/tmp/micloudxposed.apk
  chmod 644 /data/local/tmp/micloudxposed.apk
  pm install -r --user 0 /data/local/tmp/micloudxposed.apk
  echo "xposed install rc=$?"
  rm -f /data/local/tmp/micloudxposed.apk
else
  echo "MiCloudXposed already installed ($XV): $(pm path com.miui.port.xposed)"
fi

VECTOR_CLI=
for c in /data/adb/modules/zygisk_vector/cli /data/adb/modules/vector/cli; do
  if [ -x "$c" ]; then
    VECTOR_CLI="$c"
    break
  fi
done
if [ -n "$VECTOR_CLI" ]; then
  "$VECTOR_CLI" modules enable "$XPACKAGE" >/dev/null 2>&1
  "$VECTOR_CLI" scope set "$XPACKAGE" \
    com.miui.cloudservice/0 \
    com.miui.cloudbackup/0 \
    com.miui.micloudsync/0 \
    com.xiaomi.account/0 \
    com.xiaomi.simactivate.service/0 \
    com.miui.findmy/0 \
    com.xiaomi.finddevice/0 \
    com.miui.backup/0 \
    com.android.soundrecorder/0 \
    com.miui.gallery/0 \
    com.miui.mediaeditor/0 \
    com.xiaomi.xmsf/0 \
    com.xiaomi.xmsfkeeper/0 >/dev/null 2>&1
  echo "vector scope rc=$?"
else
  echo "Vector CLI not found; install/enable MiCloudXposed manually"
fi

# Gallery: install/update the China Java branch (4.3.1.18)
GALLERY_APK="$MODDIR/system/product/app/MiCloudGallery/MiCloudGallery.apk"
GV=$(dumpsys package com.miui.gallery 2>/dev/null | grep -m1 'versionCode=' | sed 's/.*versionCode=//; s/ .*//')
GN=$(dumpsys package com.miui.gallery 2>/dev/null | grep -m1 'versionName=' | sed 's/.*versionName=//; s/ .*//')
case "$GN" in
  *-global) NEED_GALLERY=1 ;;
  *) NEED_GALLERY=0 ;;
esac
if [ "$GV" != "4030118" ] || [ "$NEED_GALLERY" = "1" ]; then
  echo "gallery version is '$GV' ('$GN'), installing 4.3.1.18 (China)"
  cp -f "$GALLERY_APK" /data/local/tmp/micloudport_gallery.apk
  chmod 644 /data/local/tmp/micloudport_gallery.apk
  pm install -r -d --user 0 /data/local/tmp/micloudport_gallery.apk
  echo "pm install rc=$?"
  rm -f /data/local/tmp/micloudport_gallery.apk
else
  echo "gallery 4.3.1.18 (China) already installed: $(pm path com.miui.gallery)"
fi

# MediaEditor: gallery's Edit button launches com.miui.mediaeditor
EDITOR_APK="$MODDIR/system/product/app/MiMediaEditor/MiMediaEditor.apk"
EV=$(dumpsys package com.miui.mediaeditor 2>/dev/null | grep -m1 'versionCode=' | sed 's/.*versionCode=//; s/ .*//')
if [ -z "$EV" ]; then
  INSTALL_EDITOR=1
elif [ "$EV" -lt 203990083 ] 2>/dev/null; then
  INSTALL_EDITOR=1
else
  INSTALL_EDITOR=0
fi
if [ "$INSTALL_EDITOR" = "1" ]; then
  echo "mediaeditor version is '$EV', installing 2.3.0.8.3"
  cp -f "$EDITOR_APK" /data/local/tmp/micloudport_mediaeditor.apk
  chmod 644 /data/local/tmp/micloudport_mediaeditor.apk
  pm install -r --user 0 /data/local/tmp/micloudport_mediaeditor.apk
  echo "mediaeditor install rc=$?"
  rm -f /data/local/tmp/micloudport_mediaeditor.apk
else
  echo "mediaeditor $EV already installed: $(pm path com.miui.mediaeditor)"
fi
pm enable com.miui.mediaeditor >/dev/null 2>&1

pm grant com.miui.gallery android.permission.READ_MEDIA_IMAGES 2>/dev/null
pm grant com.miui.gallery android.permission.READ_MEDIA_VIDEO 2>/dev/null
pm grant com.miui.gallery android.permission.READ_MEDIA_VISUAL_USER_SELECTED 2>/dev/null
pm grant com.miui.gallery android.permission.ACCESS_MEDIA_LOCATION 2>/dev/null
pm grant com.miui.gallery android.permission.READ_MEDIA_AUDIO 2>/dev/null
pm grant com.miui.gallery android.permission.POST_NOTIFICATIONS 2>/dev/null
cmd appops set com.miui.gallery MANAGE_EXTERNAL_STORAGE allow 2>/dev/null
cmd appops set com.miui.gallery LEGACY_STORAGE allow 2>/dev/null

for p in android.permission.READ_MEDIA_IMAGES android.permission.READ_MEDIA_VIDEO android.permission.READ_MEDIA_AUDIO android.permission.ACCESS_MEDIA_LOCATION android.permission.POST_NOTIFICATIONS; do
  pm grant com.miui.mediaeditor "$p" 2>/dev/null
done
cmd appops set com.miui.mediaeditor MANAGE_EXTERNAL_STORAGE allow 2>/dev/null
cmd appops set com.miui.mediaeditor LEGACY_STORAGE allow 2>/dev/null

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
