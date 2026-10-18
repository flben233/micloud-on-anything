package com.example.micloudlauncher;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends Activity {

    private static final String GALLERY_UPDATE_URL =
            "https://memeosupdates.com/apps/com.miui.gallery/4030118";

    private static final String[][] TARGETS = {
        {"小米云服务", "com.miui.cloudservice", "com.miui.cloudservice.ui.MiCloudEntranceActivity"},
        {"云服务主页", "com.miui.cloudservice", "com.miui.cloudservice.ui.MiCloudMainActivity"},
        {"同步设置", "com.miui.cloudservice", "com.miui.cloudservice.ui.SyncDataSettingsActivity"},
        {"手动同步", "com.miui.cloudservice", "com.miui.cloudservice.ui.MiCloudManualSyncActivity"},
        {"云备份", "com.miui.cloudbackup", "com.miui.cloudbackup.ui.CloudBackupDetailActivity"},
        {"查找设备", "com.miui.cloudservice", "com.miui.cloudservice.ui.FindDeviceSettingsActivity"},
        {"小米账号", "com.xiaomi.account", "com.xiaomi.account.ui.AccountSettingsActivity"},
        {"登录页", "com.xiaomi.account", "com.xiaomi.account.ui.LoginActivity"},
        {"短信同步", "com.miui.cloudservice", "com.miui.cloudservice.mms.MmsSyncSettingsActivity"},
        {"联系人同步", "com.miui.cloudservice", "com.miui.cloudservice.contacts.ContactCloudSettings"},
        {"通话记录同步", "com.miui.cloudservice", "com.miui.cloudservice.calllog.CallLogSyncSettingsActivity"},
        {"录音云同步", "com.miui.cloudservice", "com.miui.cloudservice.soundrecorder.CloudSettingsActivity"},
        {"小米录音机", "com.android.soundrecorder", "com.android.soundrecorder.StartActivity"},
        {"小米相册", "com.miui.gallery", "com.miui.gallery.activity.HomePageActivity"},
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        final ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("小米云服务入口");
        title.setTextSize(22);
        title.setTextColor(Color.BLACK);
        title.setGravity(Gravity.CENTER);
        title.setPadding(0, 0, 0, pad);
        root.addView(title);

        for (final String[] t : TARGETS) {
            Button b = new Button(this);
            b.setText(t[0]);
            b.setAllCaps(false);
            b.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    open(t[1], t[2]);
                }
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.topMargin = pad / 2;
            root.addView(b, lp);
        }

        Button galleryDownload = new Button(this);
        galleryDownload.setText("下载/更新小米相册 APK");
        galleryDownload.setAllCaps(false);
        galleryDownload.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                openUrl(GALLERY_UPDATE_URL);
            }
        });
        LinearLayout.LayoutParams downloadLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        downloadLp.topMargin = pad / 2;
        root.addView(galleryDownload, downloadLp);

        scroll.addView(root);
        setContentView(scroll);

        final int base = pad;
        scroll.setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
            @Override
            public WindowInsets onApplyWindowInsets(View v, WindowInsets insets) {
                int top, bottom;
                if (android.os.Build.VERSION.SDK_INT >= 30) {
                    android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
                    top = bars.top;
                    bottom = bars.bottom;
                } else {
                    top = insets.getSystemWindowInsetTop();
                    bottom = insets.getSystemWindowInsetBottom();
                }
                v.setPadding(base, base + top, base, base + bottom);
                return insets;
            }
        });
        scroll.requestApplyInsets();

        if (android.os.Build.VERSION.SDK_INT >= 30) {
            getWindow().getInsetsController().setSystemBarsAppearance(
                    WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS,
                    WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS);
        }
    }

    private void openUrl(String url) {
        Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(i);
        } catch (Exception e) {
            Toast.makeText(this, "打开下载页失败: " + e, Toast.LENGTH_LONG).show();
        }
    }

    private void open(String pkg, String cls) {
        Intent i = new Intent();
        i.setComponent(new ComponentName(pkg, cls));
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(i);
        } catch (Exception e) {
            Toast.makeText(this, "打开失败: " + pkg + "/" + cls + "\n" + e, Toast.LENGTH_LONG).show();
        }
    }
}
