import os
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
ANDROID_JAR = Path(r"E:\Android\Sdk\platforms\android-37.0\android.jar")
AAPT2 = Path(r"E:\Android\Sdk\build-tools\36.0.0\aapt2.exe")
D8 = Path(r"E:\Android\Sdk\build-tools\36.0.0\d8.bat")
ZIPALIGN = Path(r"E:\Android\Sdk\build-tools\36.0.0\zipalign.exe")
APKSIGNER = Path(r"E:\Android\Sdk\build-tools\36.0.0\apksigner.bat")
JAVAC = Path(r"C:\Program Files\JetBrains\IntelliJ IDEA 2025.2.1\jbr\bin\javac.exe")
API = ROOT.parent / "inputs" / "libxposed-api-102.0.0.jar"
KEYSTORE = ROOT.parent / "inputs" / "own.jks"
OUT = ROOT.parent / "build" / "MiCloudXposed.apk"


def run(*args):
    print("[run]", " ".join(str(a) for a in args))
    subprocess.run([str(a) for a in args], check=True)


def main():
    os.environ["JAVA_HOME"] = str(JAVAC.parent.parent)
    if BUILD.exists():
        shutil.rmtree(BUILD)
    (BUILD / "classes").mkdir(parents=True)
    (BUILD / "dex").mkdir(parents=True)

    sources = sorted(str(p) for p in (ROOT / "src").rglob("*.java"))
    run(JAVAC, "-source", "8", "-target", "8",
        "-bootclasspath", ANDROID_JAR,
        "-classpath", API,
        "-d", BUILD / "classes", *sources)

    class_files = sorted(str(p) for p in (BUILD / "classes").rglob("*.class"))
    run(D8, "--min-api", "29", "--lib", ANDROID_JAR,
        "--classpath", API, "--output", BUILD / "dex", *class_files)

    run(AAPT2, "compile", "--dir", ROOT / "res", "-o", BUILD / "res.zip")
    run(AAPT2, "link", "-o", BUILD / "base.apk",
        "--manifest", ROOT / "AndroidManifest.xml",
        "-I", ANDROID_JAR,
        "--min-sdk-version", "29",
        "--target-sdk-version", "35",
        BUILD / "res.zip")

    with zipfile.ZipFile(BUILD / "base.apk", "a", zipfile.ZIP_DEFLATED) as apk:
        apk.write(BUILD / "dex" / "classes.dex", "classes.dex")
        for path in sorted((ROOT / "resources").rglob("*")):
            if path.is_file():
                apk.write(path, path.relative_to(ROOT / "resources").as_posix())

    normalized = BUILD / "normalized.apk"
    with zipfile.ZipFile(BUILD / "base.apk") as src, zipfile.ZipFile(normalized, "w") as dst:
        for info in src.infolist():
            entry = zipfile.ZipInfo(info.filename, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = info.compress_type
            entry.external_attr = info.external_attr
            entry.create_system = info.create_system
            dst.writestr(entry, src.read(info.filename))

    run(ZIPALIGN, "-f", "-p", "4", normalized, BUILD / "aligned.apk")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    run(APKSIGNER, "sign", "--ks", KEYSTORE, "--ks-key-alias", "own",
        "--ks-pass", "pass:android", "--key-pass", "pass:android",
        "--v1-signing-enabled", "true", "--v2-signing-enabled", "true",
        "--out", OUT, BUILD / "aligned.apk")
    run(APKSIGNER, "verify", OUT)
    print("built", OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()
