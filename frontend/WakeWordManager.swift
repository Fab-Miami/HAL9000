import Foundation
import Porcupine // Instructed: Add Porcupine Swift Package via SPM

class WakeWordManager {
    private var porcupineManager: PorcupineManager?
    private let accessKey = "YOUR_PICOVOICE_ACCESS_KEY"
    private let keyword: Porcupine.BuiltInKeyword = .computer
    
    private unowned let appState: AppState
    
    var onWakeWordDetected: (() -> Void)?
    
    init(appState: AppState) {
        self.appState = appState
    }
    
    func start() {
        do {
            porcupineManager = try PorcupineManager(
                accessKey: accessKey,
                keyword: keyword,
                onDetection: { [weak self] keywordIndex in
                    self?.handleWakeWordDetection()
                }
            )
            
            try porcupineManager?.start()
            appState.log("Porcupine initialized and listening for wake word '\(keyword.rawValue)'.")
        } catch {
            appState.log("Porcupine initialization failed: \(error.localizedDescription)")
        }
    }
    
    func stop() {
        do {
            try porcupineManager?.stop()
            appState.log("Porcupine stopped.")
        } catch {
            appState.log("Failed to stop Porcupine: \(error.localizedDescription)")
        }
    }
    
    private func handleWakeWordDetection() {
        appState.log("Wake word detected!")
        DispatchQueue.main.async {
            self.appState.status = .listening
        }
        
        onWakeWordDetected?()
    }
}
