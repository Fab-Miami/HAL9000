import Foundation
import Speech
import AVFoundation

class WakeWordManager {
    private let speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()
    
    private unowned let appState: AppState
    private let triggerWords = ["HELLO", "HI HAL","HI", "HAL", "HOWL", "HAUL", "HELL", "HELLO", "HALL", "PAL", "HELP", "HOW", "AL"]
    
    var onWakeWordDetected: (() -> Void)?
    
    init(appState: AppState) {
        self.appState = appState
    }
    
    func start() {
        appState.log("Starting native wake word detection for '\(triggerWords[0])' (and variants)...")
        
        // Ensure recognizer is available and supports on-device
        guard let speechRecognizer = speechRecognizer, speechRecognizer.isAvailable else {
            appState.log("Speech recognizer not available.")
            return
        }
        
        do {
            try startRecording()
            appState.log("Native recognizer listening (on-device)...")
        } catch {
            appState.log("Failed to start recording: \(error.localizedDescription)")
        }
    }
    
    private func startRecording() throws {
        recognitionTask?.cancel()
        recognitionTask = nil
        
        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.playAndRecord, mode: .default, options: [.duckOthers, .defaultToSpeaker])
        try audioSession.setActive(true, options: .notifyOthersOnDeactivation)
        
        // Cancel any existing audio engine tap safely AFTER the session is active
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        
        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest = recognitionRequest else { return }
        
        recognitionRequest.shouldReportPartialResults = true
        
        // Force on-device recognition as requested
        if speechRecognizer?.supportsOnDeviceRecognition == true {
            recognitionRequest.requiresOnDeviceRecognition = true
        }
        
        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)
        
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { (buffer, _) in
            recognitionRequest.append(buffer)
        }


        
        audioEngine.prepare()
        try audioEngine.start()
        
        recognitionTask = speechRecognizer?.recognitionTask(with: recognitionRequest) { [weak self] result, error in
            guard let self = self else { return }
            
            if let result = result {
                let transcription = result.bestTranscription.formattedString.uppercased()
                self.appState.log("Heard: \(transcription)") // Debug
                
                let matches = self.triggerWords.contains { transcription.contains($0) }
                
                // If conversation is active, ANY spoken text triggers the upload
                if self.appState.isConversationActive && !transcription.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    self.appState.log("Conversation is active. Triggering on any speech.")
                    self.handleWakeWordDetection()
                } else if matches {
                    self.handleWakeWordDetection()
                }
            }
            
            if error != nil || result?.isFinal == true {
                self.audioEngine.stop()
                inputNode.removeTap(onBus: 0)
                self.recognitionRequest = nil
                self.recognitionTask = nil
                
                // If it stopped due to timeout but we are still in idle, restart
                if self.appState.status == .idle {
                    try? self.startRecording()
                }
            }
        }
    }
    
    func stop() {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        appState.log("Native recognizer stopped.")
    }
    
    private func handleWakeWordDetection() {
        // Stop listening to prevent self-triggering during conversation
        stop()
        
        appState.log("Wake word detected!")
        DispatchQueue.main.async {
            self.appState.status = .listening
            self.onWakeWordDetected?()
        }
    }
}

