package com.miui.port.cloudid;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;

public class CloudIdProvider extends ContentProvider {
    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public Bundle call(String method, String arg, Bundle extras) {
        Bundle result = new Bundle();
        if ("getCloudId".equals(method)) {
            String id = null;
            try {
                Context context = getContext();
                if (context != null) {
                    id = Settings.Secure.getString(context.getContentResolver(), Settings.Secure.ANDROID_ID);
                }
            } catch (Throwable ignored) {
            }
            if (id == null || id.isEmpty()) {
                id = "micloudport";
            }
            result.putString("result_id", id);
        }
        return result;
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection, String[] selectionArgs, String sortOrder) {
        return null;
    }

    @Override
    public String getType(Uri uri) {
        return null;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        return 0;
    }
}
