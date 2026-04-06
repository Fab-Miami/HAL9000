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
                            // Stop recording now that the server is replying
                            self?.audioManager.stopTapping()
                            self?.appState.status = .processing
                            self?.audioPlayerManager.play(pcmData: data)
                        }
                        
                        self.webSocketManager.onStringReceived = { [weak self] text in
                            if text == "DONE" {
                                self?.appState.log("Received DONE signal from server.")
                                self?.audioPlayerManager.finishStream()
                            }
                        }
                        
                        self.audioPlayerManager.onPlaybackFinished = { [weak self] in
                            self?.stopInteraction()
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

    private var conversationTimer: Timer?
    
    private func handleWakeWord() {
        // Step 1: Trigger WebSocket to connect (if not already connected)
        webSocketManager.connect()
        
        // Stop any trailing conversation timer since we're actively handling a response
        conversationTimer?.invalidate()
        conversationTimer = nil
        
        // Step 2: Trigger the AudioManager to start tapping the mic
        audioManager.startTapping()
        
        // NOTE: We no longer use a simulated timeout. 
        // We stop tapping the microphone when `onAudioReceived` fires.
    }
    
    private func stopInteraction() {
        webSocketManager.disconnect()
        appState.status = .idle
        
        // Start intelligent 120s VAD listening mode
        appState.isConversationActive = true
        appState.log("Entering 120-second continuous conversation mode.")
        
        conversationTimer?.invalidate()
        conversationTimer = Timer.scheduledTimer(withTimeInterval: 120.0, repeats: false) { [weak self] _ in
            guard let self = self else { return }
            self.appState.isConversationActive = false
            self.appState.log("Conversation mode timed out. Returning to wake word only mode.")
        }
        
        // Restart wake word detection (which now acts as VAD)
        wakeWordManager.start()
    }
    
    func stop() {
        wakeWordManager.stop()
        audioManager.stopTapping()
        webSocketManager.disconnect()
    }
}
