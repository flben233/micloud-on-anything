package com.miui.port.xposed;

import android.accounts.Account;
import android.accounts.AccountManager;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.res.AssetManager;
import android.content.res.Resources;
import android.util.Base64;
import android.util.Log;

import java.io.File;
import java.lang.reflect.Array;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.WeakHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

import dalvik.system.DexClassLoader;
import io.github.libxposed.api.XposedInterface;
import io.github.libxposed.api.XposedModule;
import io.github.libxposed.api.XposedModuleInterface.ModuleLoadedParam;
import io.github.libxposed.api.XposedModuleInterface.PackageLoadedParam;
import io.github.libxposed.api.XposedModuleInterface.PackageReadyParam;

/**
 * Injects the MIUI framework dex files into the class loader of the ported
 * Xiaomi applications.  This deliberately does not touch BOOTCLASSPATH: a
 * broken module can only make the target app fail, while the system boots
 * normally.
 */
public final class MiCloudXposed extends XposedModule {
    private static final String TAG = "MiCloudXposed";

    private static final Set<String> TARGETS = new HashSet<>(Arrays.asList(
            "com.miui.cloudservice",
            "com.miui.cloudbackup",
            "com.miui.micloudsync",
            "com.xiaomi.account",
            "com.xiaomi.micloud.sdk",
            "com.xiaomi.simactivate.service",
            "com.miui.findmy",
            "com.xiaomi.finddevice",
            "com.miui.backup",
            "com.android.soundrecorder",
            "com.miui.gallery",
            "com.miui.mediaeditor",
            "com.xiaomi.xmsf",
            "com.xiaomi.xmsfkeeper"
    ));

    private static final String[] JARS = new String[]{
            "/system_ext/framework/androidx-core-stub.jar",
            "/system_ext/framework/rom-framework.jar",
            "/system_ext/framework/miui-framework.jar",
            "/system_ext/framework/miui-telephony-common.jar",
            "/system_ext/framework/miui-enterprise-sdk.jar",
            "/system_ext/framework/xiaomi-framework.jar",
            "/system_ext/framework/xm-telephony-common.jar",
            "/system_ext/framework/xm-telephony-base.jar",
            "/system_ext/framework/vendor.xiaomi.hardware.videoservice-V9-java.jar",
            "/system_ext/framework/MiuiSystemCls.jar",
            "/system_ext/framework/gson.jar",
            "/system_ext/framework/security-device-credential-sdk.jar",
            "/system_ext/framework/micloud-framework-patch.jar"
    };

    private static final String FRAMEWORK_EXT_RES =
            "/system_ext/framework/framework-ext-res/framework-ext-res.apk";
    private static final int MIUI_NOTIFICATION_COLOR = 0x11060002;

    private static final WeakHashMap<ClassLoader, Boolean> INJECTED = new WeakHashMap<>();
    private static final Set<Class<?>> MISYNC_HOOKED =
            Collections.newSetFromMap(new WeakHashMap<Class<?>, Boolean>());
    private static final Set<Class<?>> SYNC_STATUS_HOOKED =
            Collections.newSetFromMap(new WeakHashMap<Class<?>, Boolean>());
    private static final Set<Class<?>> SMS_SCHEMA_HOOKED =
            Collections.newSetFromMap(new WeakHashMap<Class<?>, Boolean>());
    private static final Object LOCK = new Object();
    private static final AtomicBoolean HIDDEN_API_DONE = new AtomicBoolean(false);
    private static final AtomicBoolean APPLOADERS_HOOK_DONE = new AtomicBoolean(false);
    private static final AtomicBoolean EXT_RES_DONE = new AtomicBoolean(false);
    private static final AtomicBoolean FINDDEVICE_SENDER_HOOK_DONE = new AtomicBoolean(false);
    private static final AtomicBoolean FINDDEVICE_STORAGE_HOOK_DONE = new AtomicBoolean(false);
    private static final AtomicBoolean SOUNDRECORDER_CTA_HOOK_DONE = new AtomicBoolean(false);
    private static final AtomicBoolean CLOUD_SETTINGS_HOOK_DONE = new AtomicBoolean(false);
    private static final AtomicBoolean CLOUD_SYNC_AUTO_VERSION_HOOK_DONE = new AtomicBoolean(false);
    private static final AtomicBoolean GALLERY_BIND_CPU_HOOK_DONE = new AtomicBoolean(false);
    private static final AtomicBoolean MEDIAEDITOR_PRO_HOOK_DONE = new AtomicBoolean(false);
    private static final AtomicBoolean MEDIAEDITOR_DEVICE_HOOK_DONE = new AtomicBoolean(false);
    private static final AtomicBoolean SIMACTIVATE_TELEPHONY_HOOK_DONE = new AtomicBoolean(false);
    private static final String FINDDEVICE_STORE = "micloudport_finddevice_store";

    @Override
    public void onModuleLoaded(ModuleLoadedParam param) {
        log(Log.INFO, TAG, "loaded in " + param.getProcessName()
                + " api=" + getApiVersion() + " framework=" + getFrameworkName());
        bypassHiddenApi();
        installApplicationLoadersHook();
    }

    @Override
    public void onPackageLoaded(PackageLoadedParam param) {
        String packageName = param.getPackageName();
        if (!TARGETS.contains(packageName)) {
            return;
        }
        injectForPackage(packageName, param.getDefaultClassLoader(),
                param.getApplicationInfo(), "loaded");
    }

    @Override
    public void onPackageReady(PackageReadyParam param) {
        String packageName = param.getPackageName();
        if (!TARGETS.contains(packageName)) {
            return;
        }
        injectForPackage(packageName, param.getClassLoader(),
                param.getApplicationInfo(), "ready");
    }

    /**
     * Shared libraries such as RtMiCloudSDK get a separate PathClassLoader
     * whose parent is normally the boot class loader.  That loader does not
     * see the jars injected into the application loader, which is why
     * miui.telephony.SubscriptionManager used to be missing inside the SDK.
     */
    private void installApplicationLoadersHook() {
        if (!APPLOADERS_HOOK_DONE.compareAndSet(false, true)) {
            return;
        }
        try {
            Class<?> loaders = Class.forName("android.app.ApplicationLoaders");
            Method method = loaders.getDeclaredMethod("getClassLoader",
                    String.class, int.class, boolean.class,
                    String.class, String.class, ClassLoader.class, String.class);
            hook(method).intercept(sharedLibraryHooker());

            Method shared = loaders.getDeclaredMethod(
                    "getSharedLibraryClassLoaderWithSharedLibraries",
                    String.class, int.class, boolean.class,
                    String.class, String.class, ClassLoader.class,
                    String.class, List.class, List.class);
            hook(shared).intercept(sharedLibraryHooker());
            log(Log.INFO, TAG, "ApplicationLoaders hooks installed");
        } catch (Throwable t) {
            log(Log.WARN, TAG, "ApplicationLoaders hook failed: " + t);
        }
    }

    private XposedInterface.Hooker sharedLibraryHooker() {
        return new XposedInterface.Hooker() {
            @Override
            public Object intercept(XposedInterface.Chain chain) throws Throwable {
                Object result = chain.proceed();
                if (result instanceof ClassLoader) {
                    String zip = (String) chain.getArg(0);
                    if (zip != null && zip.contains("RtMiCloudSDK.apk")) {
                        String cacheDir = (String) chain.getArg(4);
                        injectSharedLibrary((ClassLoader) result, cacheDir, zip);
                    }
                }
                return result;
            }
        };
    }

    private void injectSharedLibrary(ClassLoader target, String cacheDir,
            String label) {
        synchronized (LOCK) {
            if (INJECTED.containsKey(target)) {
                return;
            }
        }
        if (cacheDir == null || cacheDir.isEmpty()) {
            log(Log.WARN, TAG, label + ": no cache dir");
            return;
        }
        File cache = new File(cacheDir, "micloud-xposed-shared");
        if (!cache.isDirectory() && !cache.mkdirs()) {
            log(Log.WARN, TAG, label + ": cannot create " + cache);
            return;
        }
        String dexPath = sharedJarPath();
        if (dexPath == null) {
            log(Log.ERROR, TAG, label + ": no MIUI jars are mounted");
            return;
        }
        try {
            injectInto(target, dexPath, cache, label, "shared");
            try {
                Class.forName("miui.telephony.SubscriptionManager", false, target);
                log(Log.INFO, TAG, label + ": SubscriptionManager resolved");
            } catch (Throwable t) {
                log(Log.ERROR, TAG, label + ": SubscriptionManager still missing", t);
            }
        } catch (Throwable t) {
            log(Log.ERROR, TAG, label + ": shared injection failed", t);
        }
    }

    private static String jarPath() {
        StringBuilder builder = new StringBuilder();
        for (String path : JARS) {
            File file = new File(path);
            if (!file.isFile()) {
                continue;
            }
            if (builder.length() > 0) {
                builder.append(File.pathSeparatorChar);
            }
            builder.append(path);
        }
        return builder.length() == 0 ? null : builder.toString();
    }

    private static String sharedJarPath() {
        StringBuilder builder = new StringBuilder();
        for (String path : JARS) {
            if (path.endsWith("/gson.jar")) {
                continue;
            }
            File file = new File(path);
            if (!file.isFile()) {
                continue;
            }
            if (builder.length() > 0) {
                builder.append(File.pathSeparatorChar);
            }
            builder.append(path);
        }
        return builder.length() == 0 ? null : builder.toString();
    }

    private void installFrameworkExtResources() {
        if (!EXT_RES_DONE.compareAndSet(false, true)) {
            return;
        }
        File apk = new File(FRAMEWORK_EXT_RES);
        if (!apk.isFile()) {
            log(Log.WARN, TAG, "framework-ext-res is not mounted: " + FRAMEWORK_EXT_RES);
            return;
        }
        try {
            Resources resources = Resources.getSystem();
            AssetManager assets = resources.getAssets();
            Method add = AssetManager.class.getDeclaredMethod("addAssetPath", String.class);
            add.setAccessible(true);
            Object cookie = add.invoke(assets, apk.getAbsolutePath());
            resources.updateConfiguration(resources.getConfiguration(),
                    resources.getDisplayMetrics());
            log(Log.INFO, TAG, "framework-ext-res added: cookie=" + cookie);
            try {
                int color = resources.getColor(MIUI_NOTIFICATION_COLOR);
                log(Log.INFO, TAG, "MiuiSettings color resolved: "
                        + Integer.toHexString(color));
            } catch (Throwable t) {
                log(Log.ERROR, TAG, "MiuiSettings color still missing", t);
            }
        } catch (Throwable t) {
            log(Log.ERROR, TAG, "framework-ext-res injection failed", t);
        }
    }

    private void installMiSyncPolicyHooks(ClassLoader host) {
        final Class<?> resolver;
        try {
            resolver = Class.forName("android.content.MiSyncPolicyResolver", false, host);
        } catch (Throwable t) {
            return;
        }
        synchronized (LOCK) {
            if (!MISYNC_HOOKED.add(resolver)) {
                return;
            }
        }
        int hooked = 0;
        for (Method method : resolver.getDeclaredMethods()) {
            String name = method.getName();
            if (!"getMiSyncPauseToTime".equals(name)
                    && !"getMiSyncStrategy".equals(name)
                    && !"setMiSyncPauseToTime".equals(name)
                    && !"setMiSyncResume".equals(name)
                    && !"setMiSyncStrategy".equals(name)) {
                continue;
            }
            try {
                final Object value = defaultValue(method.getReturnType());
                hook(method).intercept(new XposedInterface.Hooker() {
                    @Override
                    public Object intercept(XposedInterface.Chain chain) throws Throwable {
                        return value;
                    }
                });
                hooked++;
            } catch (Throwable t) {
                log(Log.WARN, TAG, "MiSyncPolicy hook failed: " + method + ": " + t);
            }
        }
        log(Log.INFO, TAG, "MiSyncPolicy hooks installed: " + hooked);
    }

    /**
     * MIUI's SyncStatusInfo has an extra miSyncStatusInfo field that does not
     * exist in AOSP.  RtMiCloudSDK reads it directly from two accessors, so
     * every cloud summary/sync page used to crash with NoSuchFieldError.
     */
    private void installMiCloudSyncStatusHooks(ClassLoader host) {
        final Class<?> status;
        try {
            status = Class.forName("miui.cloud.content.MiCloudSyncStatusInfo", false, host);
        } catch (Throwable t) {
            return;
        }
        synchronized (LOCK) {
            if (!SYNC_STATUS_HOOKED.add(status)) {
                return;
            }
        }
        int hooked = 0;
        try {
            Method message = status.getDeclaredMethod("getLastResultMessage");
            hook(message).intercept(new XposedInterface.Hooker() {
                @Override
                public Object intercept(XposedInterface.Chain chain) throws Throwable {
                    return "";
                }
            });
            hooked++;
        } catch (Throwable t) {
            log(Log.WARN, TAG, "getLastResultMessage hook failed: " + t);
        }
        try {
            Method error = status.getDeclaredMethod("convertLastSyncMesgToInt");
            hook(error).intercept(new XposedInterface.Hooker() {
                @Override
                public Object intercept(XposedInterface.Chain chain) throws Throwable {
                    return Integer.valueOf(0);
                }
            });
            hooked++;
        } catch (Throwable t) {
            log(Log.WARN, TAG, "convertLastSyncMesgToInt hook failed: " + t);
        }
        log(Log.INFO, TAG, "MiCloudSyncStatusInfo hooks installed: " + hooked);
    }

    private void installSmsSchemaHooks(ClassLoader host) {
        final Class<?> provider;
        try {
            provider = Class.forName(
                    "miui.cloud.sync.providers.SmsSyncInfoProvider", false, host);
        } catch (Throwable t) {
            return;
        }
        synchronized (LOCK) {
            if (!SMS_SCHEMA_HOOKED.add(provider)) {
                return;
            }
        }
        try {
            Method simOrSubId = provider.getDeclaredMethod("getSimOrSubId");
            hook(simOrSubId).intercept(new XposedInterface.Hooker() {
                @Override
                public Object intercept(XposedInterface.Chain chain) throws Throwable {
                    return "sub_id";
                }
            });
            log(Log.INFO, TAG, "SmsSyncInfoProvider schema hook installed");
        } catch (Throwable t) {
            log(Log.WARN, TAG, "SmsSyncInfoProvider schema hook failed: " + t);
        }
    }

    private static Object defaultValue(Class<?> type) {
        if (type == int.class) {
            return Integer.valueOf(0);
        }
        if (type == long.class) {
            return Long.valueOf(0L);
        }
        if (type == boolean.class) {
            return Boolean.FALSE;
        }
        return null;
    }

    /**
     * The recorder stores its China CTA acceptance in a prefs file that the
     * app itself rewrites after the first launch.  Preseeding works once, but
     * subsequent launches see only the two keys the app keeps and silently
     * refuse to record.  Hook the acceptance check instead.
     */
    private void installSoundRecorderCtaHook(ClassLoader host) {
        if (SOUNDRECORDER_CTA_HOOK_DONE.get()) {
            return;
        }
        try {
            Class<?> settings = Class.forName(
                    "com.android.soundrecorder.SoundRecorderSettings", false, host);
            Method accepted = settings.getDeclaredMethod("F1", boolean.class);
            hook(accepted).intercept(new XposedInterface.Hooker() {
                @Override
                public Object intercept(XposedInterface.Chain chain) throws Throwable {
                    return Boolean.TRUE;
                }
            });
            SOUNDRECORDER_CTA_HOOK_DONE.set(true);
            log(Log.INFO, TAG, "SoundRecorder CTA hook installed");
        } catch (Throwable t) {
            log(Log.WARN, TAG, "SoundRecorder CTA hook not ready: " + t);
        }
    }

    private void installCloudSettingsExtrasHook(ClassLoader host) {
        if (CLOUD_SETTINGS_HOOK_DONE.get()) {
            return;
        }
        try {
            Class<?> base = Class.forName("T2.f", false, host);
            Method validate = base.getDeclaredMethod("Y");
            hook(validate).intercept(new XposedInterface.Hooker() {
                @Override
                public Object intercept(XposedInterface.Chain chain) throws Throwable {
                    Object target = chain.getThisObject();
                    if (target instanceof Activity) {
                        fillCloudSettingsExtras((Activity) target);
                    }
                    return chain.proceed();
                }
            });
            CLOUD_SETTINGS_HOOK_DONE.set(true);
            log(Log.INFO, TAG, "CloudSettings extras hook installed");
        } catch (Throwable t) {
            log(Log.WARN, TAG, "CloudSettings extras hook not ready: " + t);
        }
    }

    /**
     * Toggling a cloud sync switch calls c5.h.d(), which persists a
     * "<authority>_sync_auto_version" counter in Settings.Global.  The cloud
     * service is not a privileged app on AOSP and has no
     * WRITE_SECURE_SETTINGS, so the framework SecurityException kills the
     * process.  The value is only a local sync-policy hint; skip the write.
     */
    private void installCloudSyncAutoVersionHook(ClassLoader host) {
        if (CLOUD_SYNC_AUTO_VERSION_HOOK_DONE.get()) {
            return;
        }
        try {
            Class<?> helper = Class.forName("c5.h", false, host);
            Method write = helper.getDeclaredMethod(
                    "d", Context.class, String.class, int.class);
            hook(write).intercept(new XposedInterface.Hooker() {
                @Override
                public Object intercept(XposedInterface.Chain chain) throws Throwable {
                    log(Log.INFO, TAG, "skip Settings.Global sync_auto_version for "
                            + chain.getArg(1) + "=" + chain.getArg(2));
                    return null;
                }
            });
            CLOUD_SYNC_AUTO_VERSION_HOOK_DONE.set(true);
            log(Log.INFO, TAG, "Cloud sync auto-version hook installed");
        } catch (Throwable t) {
            log(Log.WARN, TAG, "Cloud sync auto-version hook failed: " + t);
        }
    }

    /**
     * Gallery's BindCPUCoreUtils tries to load libbindcore.so and then calls
     * its JNI bindCPU() from a HandlerThread.  The arm64 library is present in
     * the APK but is not resolvable through the translated native bridge, so
     * the background call raises UnsatisfiedLinkError and kills the process
     * when a photo is opened.  Core affinity is only a performance hint.
     */
    private void installGalleryBindCpuHook(ClassLoader host) {
        if (GALLERY_BIND_CPU_HOOK_DONE.get()) {
            return;
        }
        try {
            Class<?> utils = Class.forName(
                    "com.miui.gallery.assistant.utils.BindCPUCoreUtils", false, host);
            hook(utils.getDeclaredMethod("bindCPU", int.class, int.class))
                    .intercept(new XposedInterface.Hooker() {
                        @Override
                        public Object intercept(XposedInterface.Chain chain) {
                            return Integer.valueOf(0);
                        }
                    });
            try {
                hook(utils.getDeclaredMethod("bindCPUs", int.class, int[].class))
                        .intercept(new XposedInterface.Hooker() {
                            @Override
                            public Object intercept(XposedInterface.Chain chain) {
                                return Integer.valueOf(0);
                            }
                        });
            } catch (Throwable ignored) {
            }
            try {
                hook(utils.getDeclaredMethod("shieldCPU", int.class, int.class))
                        .intercept(new XposedInterface.Hooker() {
                            @Override
                            public Object intercept(XposedInterface.Chain chain) {
                                return Integer.valueOf(0);
                            }
                        });
            } catch (Throwable ignored) {
            }
            GALLERY_BIND_CPU_HOOK_DONE.set(true);
            log(Log.INFO, TAG, "Gallery BindCPUCoreUtils hook installed");
        } catch (Throwable t) {
            log(Log.WARN, TAG, "Gallery BindCPUCoreUtils hook failed: " + t);
        }
    }

    /**
     * MediaEditor removes the AI Erase Pro (/remover2/provider) entry when
     * Db.a.c() reports that the device is not a supported high-end model.
     * That check is a Xiaomi model whitelist plus a 4.5 GB RAM threshold, so
     * non-Xiaomi devices such as the RedMagic are treated as low-end even
     * when they have plenty of RAM.  The entry is only a navigation gate;
     * the actual model download and inference still run their own checks.
     */
    private void installMediaEditorProHooks(ClassLoader host) {
        installMediaEditorDeviceSpoof(host);
        if (MEDIAEDITOR_PRO_HOOK_DONE.get()) {
            return;
        }
        try {
            Class<?> deviceSupport = Class.forName("Db.a", false, host);
            hook(deviceSupport.getDeclaredMethod("c"))
                    .intercept(new XposedInterface.Hooker() {
                        @Override
                        public Object intercept(XposedInterface.Chain chain) {
                            return Boolean.TRUE;
                        }
                    });
            MEDIAEDITOR_PRO_HOOK_DONE.set(true);
            log(Log.INFO, TAG, "MediaEditor AI Erase Pro gate hook installed");
        } catch (Throwable t) {
            log(Log.WARN, TAG, "MediaEditor AI Erase Pro hook failed: " + t);
        }
    }

    /**
     * MediaEditor has many Xiaomi-only feature gates that compare
     * android.os.Build.DEVICE against hard-coded model lists (B0.b.x,
     * zb.l, zb.c, zb.q, and the superportrait list in Bb.c.b).  The module
     * sets ro.product.mod_device=nezha, but Build.DEVICE still reports the
     * real NX809J on RedMagic, so only /creative and /remover2 survive.
     * Make this process see the target Xiaomi codename and keep small
     * fallback hooks for the common boolean gates.
     */
    private void installMediaEditorDeviceSpoof(ClassLoader host) {
        if (!MEDIAEDITOR_DEVICE_HOOK_DONE.compareAndSet(false, true)) {
            return;
        }
        final String device = "nezha";
        try {
            Class<?> build = Class.forName("android.os.Build", false, host);
            setStaticField(build, "DEVICE", device);
            log(Log.INFO, TAG, "MediaEditor Build.DEVICE spoof installed: " + device);
        } catch (Throwable t) {
            log(Log.WARN, TAG, "MediaEditor Build.DEVICE spoof failed: " + t);
        }
        hookBoolean(host, "B0.b", "x", "device support");
        hookBoolean(host, "B0.b", "v", "CN region");
        hookBoolean(host, "zb.q", "a", "sky");
        hookBoolean(host, "D8.j", "p", "beautification");

        try {
            Class<?> matting = Class.forName("zb.l", false, host);
            for (Field field : matting.getDeclaredFields()) {
                if (field.getType() == Boolean.TYPE) {
                    field.setAccessible(true);
                    field.setBoolean(null, true);
                    log(Log.INFO, TAG, "MediaEditor matting support enabled");
                }
            }
        } catch (Throwable t) {
            log(Log.WARN, TAG, "MediaEditor matting gate failed: " + t);
        }

        try {
            Class<?> bokeh = Class.forName("zb.c", false, host);
            for (Field field : bokeh.getDeclaredFields()) {
                if (!Set.class.isAssignableFrom(field.getType())) {
                    continue;
                }
                field.setAccessible(true);
                Object value = field.get(null);
                if (value instanceof Set) {
                    Set<String> devices = (Set<String>) value;
                    devices.add(device);
                    devices.add(android.os.Build.DEVICE);
                    log(Log.INFO, TAG, "MediaEditor bokeh device added");
                }
            }
        } catch (Throwable t) {
            log(Log.WARN, TAG, "MediaEditor bokeh gate failed: " + t);
        }
    }

    private void hookBoolean(ClassLoader host, String className, String methodName,
            String label) {
        try {
            Class<?> clazz = Class.forName(className, false, host);
            hook(clazz.getDeclaredMethod(methodName))
                    .intercept(new XposedInterface.Hooker() {
                        @Override
                        public Object intercept(XposedInterface.Chain chain) {
                            return Boolean.TRUE;
                        }
                    });
            log(Log.INFO, TAG, "MediaEditor " + label + " gate hooked");
        } catch (Throwable t) {
            log(Log.WARN, TAG, "MediaEditor " + label + " gate failed: " + t);
        }
    }

    /**
     * Android 16 only allows subscriber identifiers for apps holding
     * READ_PRIVILEGED_PHONE_STATE, a carrier privilege, or the signature
     * USE_ICC_AUTH_WITH_DEVICE_IDENTIFIER app-op.  SimActivate is a normal
     * /product/app, so its IActivateService.getActivateInfo2() fails with
     * SecurityException; Binder forwards that exception into cloudservice and
     * MiCloudEntranceActivity dies.  The activation-info path already treats
     * an empty SIM as "not inserted", so swallow the denial there.  If the
     * device actually grants access, the real value is returned unchanged.
     */
    private void installSimActivateTelephonyHooks(ClassLoader host) {
        if (SIMACTIVATE_TELEPHONY_HOOK_DONE.get()) {
            return;
        }
        try {
            Class<?> telephony = Class.forName("j1.r", false, host);
            int hooked = 0;
            for (final String name : new String[]{"l", "i", "c"}) {
                try {
                    Method method = telephony.getDeclaredMethod(name, int.class);
                    hook(method).intercept(new XposedInterface.Hooker() {
                        @Override
                        public Object intercept(XposedInterface.Chain chain)
                                throws Throwable {
                            try {
                                return chain.proceed();
                            } catch (SecurityException e) {
                                log(Log.WARN, TAG, "simactivate telephony "
                                        + name + " denied for subId "
                                        + chain.getArg(0) + ": " + e.getMessage());
                                return null;
                            }
                        }
                    });
                    hooked++;
                } catch (Throwable t) {
                    log(Log.WARN, TAG, "simactivate telephony hook "
                            + name + " failed: " + t);
                }
            }
            SIMACTIVATE_TELEPHONY_HOOK_DONE.set(hooked > 0);
            log(Log.INFO, TAG, "simactivate telephony hooks installed: " + hooked);
        } catch (Throwable t) {
            log(Log.WARN, TAG, "simactivate telephony hooks failed: " + t);
        }
    }

    private static void fillCloudSettingsExtras(Activity activity) {
        Intent intent = activity.getIntent();
        if (intent == null) {
            return;
        }
        String authority = intent.getStringExtra("authority");
        if (authority == null) {
            String cls = activity.getClass().getName();
            if (cls.contains(".mms.")) {
                authority = "sms";
            } else if (cls.contains(".contacts.")) {
                authority = "com.android.contacts";
            } else if (cls.contains(".calllog.")) {
                authority = "call_log";
            } else if (cls.contains(".soundrecorder.")) {
                authority = "records";
            }
            if (authority != null) {
                intent.putExtra("authority", authority);
            }
        }
        if (intent.getParcelableExtra("account") == null) {
            Account[] accounts = AccountManager.get(activity)
                    .getAccountsByType("com.xiaomi");
            if (accounts.length > 0) {
                intent.putExtra("account", accounts[0]);
            }
        }
    }

    private void installFindDeviceSenderHook(ClassLoader host) {
        if (FINDDEVICE_SENDER_HOOK_DONE.get()) {
            return;
        }
        try {
            Class<?> wrapper = Class.forName("vv.d", false, host);
            Method senderMethod = wrapper.getDeclaredMethod("a", Intent.class);
            hook(senderMethod).intercept(new XposedInterface.Hooker() {
                @Override
                public Object intercept(XposedInterface.Chain chain) throws Throwable {
                    Intent intent = (Intent) chain.getArg(0);
                    String sender = intent == null ? null : intent.getPackage();
                    if (sender == null && intent != null) {
                        String action = intent.getAction();
                        if ("android.accounts.LOGIN_ACCOUNTS_POST_CHANGED".equals(action)
                                || "android.accounts.LOGIN_ACCOUNTS_CHANGED".equals(action)) {
                            sender = "com.xiaomi.account";
                        }
                    }
                    return sender;
                }
            });
            FINDDEVICE_SENDER_HOOK_DONE.set(true);
            log(Log.INFO, TAG, "finddevice sender hook installed");
        } catch (Throwable t) {
            log(Log.WARN, TAG, "finddevice sender hook failed: " + t);
        }
    }

    /**
     * FindDevice stores its device credentials and status through the vendor
     * MTD service (or the legacy eb0 fallback).  Neither exists on AOSP, and
     * xd.e.a() retries forever while the FindDeviceStatusManager/F
     * class locks are held, which deadlocks the whole app.  Persist the same
     * blobs in app-private SharedPreferences instead.
     */
    private void installFindDeviceStorageHooks(ClassLoader host) {
        if (FINDDEVICE_STORAGE_HOOK_DONE.get()) {
            return;
        }
        try {
            Class<?> store = Class.forName("xd.e", false, host);
            final Class<?> handler = Class.forName("yd.i$b", false, host);
            final Method onHandle = handler.getMethod("onHandleData", byte[].class);
            onHandle.setAccessible(true);

            hook(store.getDeclaredMethod("a")).intercept(new XposedInterface.Hooker() {
                @Override
                public Object intercept(XposedInterface.Chain chain) {
                    return Boolean.TRUE;
                }
            });
            hook(store.getDeclaredMethod("b", Context.class, String.class))
                    .intercept(new XposedInterface.Hooker() {
                        @Override
                        public Object intercept(XposedInterface.Chain chain) {
                            Context ctx = (Context) chain.getArg(0);
                            String name = (String) chain.getArg(1);
                            fdStore(ctx).edit().remove(name).commit();
                            return null;
                        }
                    });
            hook(store.getDeclaredMethod("c", Context.class, String.class, handler))
                    .intercept(new XposedInterface.Hooker() {
                        @Override
                        public Object intercept(XposedInterface.Chain chain) {
                            Context ctx = (Context) chain.getArg(0);
                            String name = (String) chain.getArg(1);
                            Object dataHandler = chain.getArg(2);
                            String encoded = fdStore(ctx).getString(name, null);
                            if (encoded == null) {
                                return null;
                            }
                            try {
                                byte[] data = Base64.decode(encoded, Base64.NO_WRAP);
                                onHandle.invoke(dataHandler, (Object) data);
                            } catch (InvocationTargetException e) {
                                log(Log.WARN, TAG, "fd store handler failed for "
                                        + name + ": " + e.getCause());
                            } catch (Throwable t) {
                                log(Log.WARN, TAG, "fd store read failed for "
                                        + name + ": " + t);
                            }
                            return null;
                        }
                    });
            hook(store.getDeclaredMethod("d", Context.class, String.class, byte[].class))
                    .intercept(new XposedInterface.Hooker() {
                        @Override
                        public Object intercept(XposedInterface.Chain chain) {
                            Context ctx = (Context) chain.getArg(0);
                            String name = (String) chain.getArg(1);
                            byte[] data = (byte[]) chain.getArg(2);
                            String encoded = Base64.encodeToString(data, Base64.NO_WRAP);
                            fdStore(ctx).edit().putString(name, encoded).commit();
                            return null;
                        }
                    });
            FINDDEVICE_STORAGE_HOOK_DONE.set(true);
            log(Log.INFO, TAG, "finddevice storage fallback installed");
        } catch (Throwable t) {
            log(Log.WARN, TAG, "finddevice storage hook failed: " + t);
        }
    }

    private static SharedPreferences fdStore(Context ctx) {
        return ctx.getSharedPreferences(FINDDEVICE_STORE, Context.MODE_PRIVATE);
    }

    private void injectForPackage(String packageName, ClassLoader host,
            ApplicationInfo info, String phase) {
        if (host == null) {
            log(Log.WARN, TAG, packageName + ": null class loader");
            return;
        }
        if ("com.xiaomi.finddevice".equals(packageName)) {
            installFindDeviceSenderHook(host);
            installFindDeviceStorageHooks(host);
        }
        if ("com.android.soundrecorder".equals(packageName)) {
            installSoundRecorderCtaHook(host);
        }
        if ("com.xiaomi.simactivate.service".equals(packageName)) {
            installSimActivateTelephonyHooks(host);
        }
        if ("com.miui.cloudservice".equals(packageName)) {
            installCloudSettingsExtrasHook(host);
            installCloudSyncAutoVersionHook(host);
        }
        if ("com.miui.gallery".equals(packageName)) {
            installGalleryBindCpuHook(host);
        }
        if ("com.miui.mediaeditor".equals(packageName)) {
            installMediaEditorProHooks(host);
        }
        synchronized (LOCK) {
            if (INJECTED.containsKey(host)) {
                return;
            }
        }

        bypassHiddenApi();
        installFrameworkExtResources();

        String dataDir = info == null ? null : info.dataDir;
        if (dataDir == null || dataDir.isEmpty()) {
            log(Log.WARN, TAG, packageName + ": no data dir");
            return;
        }

        StringBuilder dexPathBuilder = new StringBuilder();
        StringBuilder loadedBuilder = new StringBuilder();
        for (String path : JARS) {
            File file = new File(path);
            if (!file.isFile()) {
                continue;
            }
            if (dexPathBuilder.length() > 0) {
                dexPathBuilder.append(File.pathSeparatorChar);
            }
            dexPathBuilder.append(path);
            if (loadedBuilder.length() > 0) {
                loadedBuilder.append(',');
            }
            loadedBuilder.append(file.getName());
        }
        if (dexPathBuilder.length() == 0) {
            log(Log.ERROR, TAG, packageName + ": no MIUI jars are mounted");
            return;
        }

        File cacheDir = new File(dataDir, "code_cache/micloud-xposed");
        if (!cacheDir.isDirectory() && !cacheDir.mkdirs()) {
            log(Log.ERROR, TAG, packageName + ": cannot create " + cacheDir);
            return;
        }

        try {
            injectInto(host, dexPathBuilder.toString(), cacheDir, packageName, phase);
            log(Log.INFO, TAG, packageName + ": injected " + loadedBuilder);
            try {
                Class.forName("androidx.core.app.CoreComponentFactory", false, host);
                log(Log.INFO, TAG, packageName + ": CoreComponentFactory resolved");
            } catch (Throwable t) {
                log(Log.ERROR, TAG, packageName + ": CoreComponentFactory still missing", t);
            }
            try {
                Class.forName("miui.os.Build", false, host);
                log(Log.INFO, TAG, packageName + ": miui.os.Build resolved");
            } catch (Throwable t) {
                log(Log.ERROR, TAG, packageName + ": miui.os.Build still missing", t);
            }
            try {
                Class.forName("miui.telephony.SubscriptionManager", false, host);
                log(Log.INFO, TAG, packageName + ": SubscriptionManager resolved");
            } catch (Throwable t) {
                log(Log.ERROR, TAG, packageName + ": SubscriptionManager still missing", t);
            }
        } catch (Throwable t) {
            log(Log.ERROR, TAG, packageName + ": injection failed", t);
        }
    }

    private void injectInto(ClassLoader target, String dexPath, File cacheDir,
            String label, String phase) throws Exception {
        synchronized (LOCK) {
            if (INJECTED.containsKey(target)) {
                return;
            }
        }
        DexClassLoader source = new DexClassLoader(
                dexPath, cacheDir.getAbsolutePath(), null, target);
        injectDexElements(target, source);
        synchronized (LOCK) {
            INJECTED.put(target, Boolean.TRUE);
        }
        installMiSyncPolicyHooks(target);
        installMiCloudSyncStatusHooks(target);
        installSmsSchemaHooks(target);
        log(Log.INFO, TAG, label + "/" + phase + ": injected into "
                + target.getClass().getName());
    }

    private static void injectDexElements(ClassLoader host, ClassLoader source) throws Exception {
        Object hostPathList = getField(host, "pathList");
        Object sourcePathList = getField(source, "pathList");
        Object hostElements = getField(hostPathList, "dexElements");
        Object sourceElements = getField(sourcePathList, "dexElements");
        int hostLength = Array.getLength(hostElements);
        int sourceLength = Array.getLength(sourceElements);
        Object combined = Array.newInstance(
                hostElements.getClass().getComponentType(), hostLength + sourceLength);
        System.arraycopy(hostElements, 0, combined, 0, hostLength);
        System.arraycopy(sourceElements, 0, combined, hostLength, sourceLength);
        setField(hostPathList, "dexElements", combined);
    }

    private static Object getField(Object target, String name) throws Exception {
        Field field = findField(target.getClass(), name);
        field.setAccessible(true);
        return field.get(target);
    }

    private static void setField(Object target, String name, Object value) throws Exception {
        Field field = findField(target.getClass(), name);
        field.setAccessible(true);
        field.set(target, value);
    }

    private static void setStaticField(Class<?> clazz, String name, Object value)
            throws Exception {
        Field field = findField(clazz, name);
        field.setAccessible(true);
        field.set(null, value);
    }

    private static Field findField(Class<?> clazz, String name) throws NoSuchFieldException {
        Class<?> current = clazz;
        while (current != null) {
            try {
                return current.getDeclaredField(name);
            } catch (NoSuchFieldException ignored) {
                current = current.getSuperclass();
            }
        }
        throw new NoSuchFieldException(name);
    }

    private void bypassHiddenApi() {
        if (!HIDDEN_API_DONE.compareAndSet(false, true)) {
            return;
        }
        try {
            Class<?> vmRuntime = Class.forName("dalvik.system.VMRuntime");
            Method getRuntime = vmRuntime.getDeclaredMethod("getRuntime");
            getRuntime.setAccessible(true);
            Object runtime = getRuntime.invoke(null);
            Method setExemptions = vmRuntime.getDeclaredMethod(
                    "setHiddenApiExemptions", String[].class);
            setExemptions.setAccessible(true);
            setExemptions.invoke(runtime, (Object) new String[]{"L"});
            log(Log.INFO, TAG, "hidden API exemptions installed");
        } catch (Throwable t) {
            log(Log.WARN, TAG, "hidden API exemption failed: " + t);
        }
    }
}
