#!/system/bin/sh
MODDIR=${0%/*}
LOG=/data/local/tmp/micloudport.log
exec >>"$LOG" 2>&1
echo "==== patch_account_dex $(date) ===="

APK=/product/app/MIUIXiaomiAccount/MIUIXiaomiAccount.apk
ORIG="$MODDIR/system/product/app/MIUIXiaomiAccount/MIUIXiaomiAccount.apk"
ZIP="$MODDIR/files/patched_account.zip"
[ -f "$APK" ] || { echo "account APK missing"; exit 1; }
[ -f "$ZIP" ] || { echo "patched zip missing"; exit 1; }
[ -f "$ORIG" ] || { echo "original account APK missing"; exit 1; }

restore_apk() {
  umount -l "$APK" 2>/dev/null
  mount -o bind "$ORIG" "$APK" 2>/dev/null
}
trap restore_apk EXIT

ABI=$(getprop ro.product.cpu.abi)
case "$ABI" in
  arm64-v8a) ISA=arm64 ;;
  x86_64)    ISA=x86_64 ;;
  *) echo "unsupported abi $ABI"; exit 1 ;;
esac

D=/data/dalvik-cache/$ISA
NAME='product@app@MIUIXiaomiAccount@MIUIXiaomiAccount.apk@classes'
MARKER=/data/adb/micloudport_acct_$ISA.done
APKSHA=$(sha1sum "$APK" | cut -d' ' -f1)

if [ -f "$MARKER" ] && [ "$(cat "$MARKER" 2>/dev/null)" = "$APKSHA" ] && [ -f "$D/$NAME.vdex" ]; then
  echo "account odex already patched ($APKSHA)"
  exit 0
fi

DEX2OAT=/apex/com.android.art/bin/dex2oat64
[ -x "$DEX2OAT" ] || DEX2OAT=/system/bin/dex2oat64
[ -x "$DEX2OAT" ] || { echo "dex2oat64 not found"; exit 1; }

BOOT=
for b in \
  "/data/misc/apexdata/com.android.art/dalvik-cache/$ISA/boot.art" \
  "/system/framework/$ISA/boot.art" \
  "/apex/com.android.art/javalib/$ISA/boot.art"; do
  if [ -f "$b" ]; then
    BOOT="$b"
    break
  fi
done
if [ -z "$BOOT" ]; then
  echo "boot image missing for $ISA"
  exit 1
fi
echo "using boot image: $BOOT"

TMP=/data/local/tmp/micloudport_acct
mkdir -p "$TMP" "$D"
rm -f "$TMP/out.odex" "$TMP/out.vdex"

CTX='PCL[]{PCL[/system_ext/priv-app/RtMiCloudSDK/RtMiCloudSDK.apk]'
[ -f /system/framework/org.apache.http.legacy.jar ] && CTX="$CTX#PCL[/system/framework/org.apache.http.legacy.jar]"
[ -f /system_ext/framework/androidx.window.extensions.jar ] && CTX="$CTX#PCL[/system_ext/framework/androidx.window.extensions.jar]"
[ -f /system_ext/framework/androidx.window.sidecar.jar ] && CTX="$CTX#PCL[/system_ext/framework/androidx.window.sidecar.jar]"
CTX="$CTX}"

am force-stop com.xiaomi.account
umount -l "$APK" 2>/dev/null
mount -o bind "$ZIP" "$APK" || { echo "bind mount failed"; exit 1; }

echo "compiling patched account dex ($ISA)"
"$DEX2OAT" \
  --dex-file="$APK" \
  --oat-file="$TMP/out.odex" \
  --output-vdex="$TMP/out.vdex" \
  --oat-location="$D/$NAME.dex" \
  --class-loader-context="$CTX" \
  --classpath-dir=/product/app/MIUIXiaomiAccount \
  --instruction-set="$ISA" \
  --instruction-set-features=default \
  --compiler-filter=speed \
  --compilation-reason=cmdline \
  --max-image-block-size=524288 \
  --resolve-startup-const-strings=true \
  --generate-mini-debug-info \
  --runtime-arg -Xtarget-sdk-version:35 \
  --no-allow-profile-code \
  --runtime-arg -Xms64m \
  --runtime-arg -Xmx512m \
  --boot-image="$BOOT"
RC=$?
if [ "$RC" -ne 0 ] || [ ! -s "$TMP/out.odex" ] || [ ! -s "$TMP/out.vdex" ]; then
  echo "first dex2oat attempt failed rc=$RC, retrying minimal"
  rm -f "$TMP/out.odex" "$TMP/out.vdex"
  "$DEX2OAT" \
    --dex-file="$APK" \
    --oat-file="$TMP/out.odex" \
    --output-vdex="$TMP/out.vdex" \
    --oat-location="$D/$NAME.dex" \
    --class-loader-context="$CTX" \
    --instruction-set="$ISA" \
    --compiler-filter=speed \
    --runtime-arg -Xms64m \
    --runtime-arg -Xmx512m \
    --boot-image="$BOOT"
  RC=$?
fi
if [ "$RC" -ne 0 ] || [ ! -s "$TMP/out.odex" ] || [ ! -s "$TMP/out.vdex" ]; then
  echo "dex2oat failed rc=$RC"
  exit 1
fi

VDEX="$TMP/out.vdex"
ODEX="$TMP/out.odex"

MAGIC=$(dd if="$VDEX" bs=1 count=8 2>/dev/null | od -An -tx1 | tr -d ' \n')
if [ "$MAGIC" != "7664657830323700" ]; then
  echo "unexpected vdex magic: $MAGIC"
  exit 1
fi

# vdex header: two dex checksums at 0x3c/0x40 must equal the stock APK ZIP CRCs
printf '\004\151\371\135\000\245\344\257' | dd of="$VDEX" bs=1 seek=60 conv=notrunc 2>/dev/null

# odex stub dex headers: replace patched-dex adler32 with the stock APK ZIP CRC
PATCHED=0
grep -abo dex "$ODEX" 2>/dev/null | cut -d: -f1 | while read -r OFF; do
  HDR=$(dd if="$ODEX" bs=1 skip="$OFF" count=8 2>/dev/null | od -An -tx1 | tr -d ' \n')
  [ "$HDR" = "6465780a30333900" ] || continue
  SHA=$(dd if="$ODEX" bs=1 skip=$((OFF + 12)) count=20 2>/dev/null | od -An -tx1 | tr -d ' \n')
  case "$SHA" in
    9db3327e882d6fe47972d6f6c2179730d71030b1)
      printf '\004\151\371\135' | dd of="$ODEX" bs=1 seek=$((OFF + 8)) conv=notrunc 2>/dev/null
      echo "patched odex classes.dex stub @ $OFF"
      ;;
    ebff3bd8137b03b75235eec0abf023e7aae6c4d0)
      printf '\000\245\344\257' | dd of="$ODEX" bs=1 seek=$((OFF + 8)) conv=notrunc 2>/dev/null
      echo "patched odex classes2.dex stub @ $OFF"
      ;;
  esac
done

cp -f "$ODEX" "$D/$NAME.dex"
cp -f "$VDEX" "$D/$NAME.vdex"
chown 1000:1000 "$D/$NAME.dex" "$D/$NAME.vdex" 2>/dev/null
chmod 644 "$D/$NAME.dex" "$D/$NAME.vdex"
restorecon "$D/$NAME.dex" "$D/$NAME.vdex" 2>/dev/null
chcon u:object_r:dalvikcache_data_file:s0 "$D/$NAME.dex" "$D/$NAME.vdex" 2>/dev/null

am force-stop com.xiaomi.account
echo "$APKSHA" > "$MARKER"
echo "account odex deployed"
rm -f "$TMP/out.odex" "$TMP/out.vdex"
exit 0
