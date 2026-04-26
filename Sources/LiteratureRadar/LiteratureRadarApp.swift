import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        activateMainWindow()
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        activateMainWindow()
    }

    private func activateMainWindow() {
        DispatchQueue.main.async {
            NSApp.activate()
            NSApp.windows.first?.makeKeyAndOrderFront(nil)
        }
    }
}

@main
struct LiteratureRadarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup {
            ContentView()
                .frame(minWidth: 980, minHeight: 680)
                .onAppear {
                    NSApp.activate()
                    NSApp.windows.first?.makeKeyAndOrderFront(nil)
                }
        }
        .windowStyle(.titleBar)
    }
}
