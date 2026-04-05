import SwiftUI

@main
struct HALApp: App {
    @StateObject private var coordinator = AppCoordinator()
    
    var body: some Scene {
        WindowGroup {
            ContentView(appState: coordinator.appState)
                .onAppear {
                    coordinator.start()
                }
        }
    }
}
