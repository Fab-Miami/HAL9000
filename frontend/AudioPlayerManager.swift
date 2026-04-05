import Foundation
import AVFoundation

class AudioPlayerManager {
    private let audioEngine = AVAudioEngine()
    private let playerNode = AVAudioPlayerNode()
    private let appState: AppState
    
    // Default Kokoro sample rate is 24000Hz
    private let sampleRate: Double = 24000.0
    
    init(appState: AppState) {
        self.appState = appState
        setupAudioEngine()
    }
    
    private func setupAudioEngine() {
        audioEngine.attach(playerNode)
        
        let format = AVAudioFormat(commonFormat: .pcmFormatInt16,
                                   sampleRate: sampleRate,
                                   channels: 1,
                                   interleaved: false)!
        
        audioEngine.connect(playerNode, to: audioEngine.mainMixerNode, format: format)
        
        do {
            try audioEngine.start()
        } catch {
            appState.log("Audio Engine failed to start: \(error.localizedDescription)")
        }
    }
    
    var onPlaybackFinished: (() -> Void)?
    
    // ... (rest of the file remains the same except play func) ...
    
    func play(pcmData: Data) {
        let format = AVAudioFormat(commonFormat: .pcmFormatInt16,
                                   sampleRate: sampleRate,
                                   channels: 1,
                                   interleaved: false)!
        
        let frameCount = UInt32(pcmData.count) / 2
        
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount) else {
            return
        }
        
        buffer.frameLength = frameCount
        
        pcmData.withUnsafeBytes { (rawBufferPointer: UnsafeRawBufferPointer) in
            if let address = rawBufferPointer.baseAddress {
                let int16Pointer = address.assumingMemoryBound(to: Int16.self)
                if let channelData = buffer.int16ChannelData {
                    channelData[0].update(from: int16Pointer, count: Int(frameCount))
                }
            }
        }
        
        if !audioEngine.isRunning {
            try? audioEngine.start()
        }
        
        playerNode.play()
        playerNode.scheduleBuffer(buffer) { [weak self] in
            DispatchQueue.main.async {
                print("Audio playback finished.")
                self?.onPlaybackFinished?()
            }
        }
    }
    
    func stop() {
        playerNode.stop()
        audioEngine.stop()
    }
}
