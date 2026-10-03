import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

/**
 * The Android wrapper's configuration lives in two files that must agree:
 * bubblewrap writes twa-manifest.json, and the values it generates are copied
 * into build.gradle. Regenerating one without the other is silent - the app
 * builds and installs, and the difference only shows on a device.
 *
 * This is the JS test runner in the repo, so it is where that check can live.
 */
const root = fileURLToPath(new URL("../../android/", import.meta.url))
const twa = JSON.parse(readFileSync(`${root}twa-manifest.json`, "utf8"))
const gradle = readFileSync(`${root}app/build.gradle`, "utf8")

function gradleValue(key: string): string | undefined {
  return gradle.match(new RegExp(`${key}:\\s*'([^']*)'`))?.[1]
}

describe("Android wrapper configuration", () => {
  it("falls back to a WebView, never to a Custom Tab", () => {
    // A Trusted Web Activity is verified on the device at runtime by whichever
    // browser serves it. When that verification fails - an old browser, a
    // provider that does not support TWA, no network on first launch - the
    // fallback decides what the user sees. 'customtabs' shows the browser's
    // close button and URL bar over the app; 'webview' shows nothing at all.
    // There is no site-side change that can guarantee verification succeeds,
    // so the guarantee has to come from the fallback.
    expect(twa.fallbackType).toBe("webview")
    expect(gradleValue("fallbackType")).toBe("webview")
  })

  it("points at the host the site serves asset links from", () => {
    expect(twa.host).toBe("app.vibetrading.club")
    expect(gradleValue("hostName")).toBe("app.vibetrading.club")
  })

  it("keeps the package id in step between the two files", () => {
    expect(twa.packageId).toBe("club.vibetrading.app")
    expect(gradle).toContain(`applicationId "${twa.packageId}"`)
  })

  it("uses one full app name, in both files and in both labels", () => {
    // appName labels the application (Settings, permission dialogs);
    // launcherName labels the home screen icon. Bubblewrap keeps them separate
    // so the icon can be short - here they are deliberately the same.
    expect(twa.name).toBe("VibeTrading Club")
    expect(twa.launcherName).toBe("VibeTrading Club")
    expect(gradleValue("name")).toBe(twa.name)
    expect(gradleValue("launcherName")).toBe(twa.launcherName)
  })

  it("declares a minimum SDK Play will accept", () => {
    // Play's installer check rejects the upload below 24, and bubblewrap
    // generates 21 by default - so this drifts back every time the project is
    // regenerated, and the only signal is a failed release.
    expect(twa.minSdkVersion).toBeGreaterThanOrEqual(24)
    const gradleMin = Number(gradle.match(/minSdkVersion\s+(\d+)/)?.[1])
    expect(gradleMin).toBe(twa.minSdkVersion)
  })

  it("has a version code matching the manifest, for the next Play release", () => {
    const code = Number(gradle.match(/versionCode\s+(\d+)/)?.[1])
    expect(code).toBe(twa.appVersionCode)
    expect(code).toBeGreaterThan(1)
  })

  it("trusts both the upload key and the Play App Signing key", () => {
    // Play re-signs the uploaded bundle, so the app on a user's device carries
    // a different fingerprint from the one it was built with. Both must appear
    // in the site's assetlinks.json or verification fails for everyone.
    //
    // The console's fingerprints are not proof of what a device receives: the
    // 1.2 build Play delivered was signed with FC:8A:C6:EB..., which the console
    // pages did not show. Read the real one from an installed copy:
    //   adb shell dumpsys package club.vibetrading.app | grep Signatures
    const site = JSON.parse(
      readFileSync(
        fileURLToPath(new URL("../public/.well-known/assetlinks.json", import.meta.url)),
        "utf8",
      ),
    )
    const served: string[] = site[0].target.sha256_cert_fingerprints
    for (const { value } of twa.fingerprints) {
      expect(served).toContain(value)
    }
  })
})
