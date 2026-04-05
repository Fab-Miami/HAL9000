import Foundation

class AppCoordinator: ObservableObject {
    let appState = AppState()
    
    lazy var wakeWordManager: WakeWordManager = {
        WakeWordManager(appState: self.appState)
    }()
    
    lazy var webSocketManager: WebSocketManager = {
        WebSocketManager(appState: self.appState)
    }()
    
    lazy var audioPlayerManager: AudioPlayerManager = {
        AudioPlayerManager(appState: self.appState)
    }()
    
    lazy var audioManager: AudioManager = {
        let manager = AudioManager(appState: self.appState)
        // Pass data from AudioManager immediately to WebSocketManager
        manager.onAudioDataAvailable = { [weak self] data in
            self?.webSocketManager.send(data: data)
        }
        return manager
    }()
    
    func start() {
        appState.log("App launched. Requesting permissions...")
        PermissionsManager.shared.requestMicrophonePermission { [weak self] micGranted in
            guard let self = self else { return }
            if micGranted {
                self.appState.log("Microphone permission granted.")
                PermissionsManager.shared.requestSpeechRecognitionPermission { speechGranted in
                    if speechGranted {
                        self.appState.log("Speech recognition permission granted.")
                        
                        // Set up the bridge flow when WakeWordManager hears "HAL"
                        self.wakeWordManager.onWakeWordDetected = { [weak self] in
                            self?.handleWakeWord()
                        }
                        
                        // Set up audio playback
                        self.webSocketManager.onAudioReceived = { [weak self] data in
                            self?.audioPlayerManager.play(pcmData: data)
                        }
                        
                        self.wakeWordManager.start()
                    } else {
                        self.appState.log("Speech recognition permission denied.")
                    }
                }
            } else {
                self.appState.log("Microphone permission denied.")
            }
        }
    }

    
    private func handleWakeWord() {
        // Step 1: Trigger WebSocket to connect (if not already connected)
        webSocketManager.connect()
        
        // Step 2: Trigger the AudioManager to start tapping the mic
        audioManager.startTapping()
        
        // NOTE: We no longer use a simulated timeout. 
        // The interaction continues as long as HAL is responding.
    }
    
    private func stopInteraction() {
        audioManager.stopTapping()
        appState.status = .idle
        // Restart wake word detection
        wakeWordManager.start()
    }
    
    func stop() {
        wakeWordManager.stop()
        audioManager.stopTapping()
        webSocketManager.disconnect()
    }
}
