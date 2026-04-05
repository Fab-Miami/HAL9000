import Foundation
import Speech
import AVFoundation

class WakeWordManager {
    private let speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()
    
    private unowned let appState: AppState
    private let triggerWord = "HAL"
    
    var onWakeWordDetected: (() -> Void)?
    
    init(appState: AppState) {
        self.appState = appState
    }
    
    func start() {
        appState.log("Starting native wake word detection for '\(triggerWord)'...")
        
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
        // Cancel any existing task
        recognitionTask?.cancel()
        recognitionTask = nil
        
        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.playAndRecord, mode: .measurement, options: .duckOthers)
        try audioSession.setActive(true, options: .notifyOthersOnDeactivation)
        
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
                // appState.log("Heard: \(transcription)") // Debug
                
                if transcription.contains(self.triggerWord.uppercased()) {
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
        
        appState.log("Wake word '\(triggerWord)' detected!")
        DispatchQueue.main.async {
            self.appState.status = .listening
            self.onWakeWordDetected?()
        }
    }
}

