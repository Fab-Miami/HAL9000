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
        
        let mixerFormat = audioEngine.mainMixerNode.outputFormat(forBus: 0)
        audioEngine.mainMixerNode.installTap(onBus: 0, bufferSize: 1024, format: mixerFormat) { [weak self] (buffer, _) in
            guard let self = self, self.appState.status == .processing else { return }
            
            if let channelData = buffer.floatChannelData?[0] {
                let frameLength = Int(buffer.frameLength)
                var sum: Float = 0
                for i in 0..<frameLength {
                    sum += channelData[i] * channelData[i]
                }
                let rms = sqrt(sum / Float(frameLength))
                
                // HAL is talking -> apply 1.5x amplitude multiplier for more visible UI feedback
                let normalizedIntensity = Double(min(max(rms * 5.0, 0.0), 1.0)) * 1.5
                
                DispatchQueue.main.async {
                    if self.appState.status == .processing {
                        self.appState.intensity = normalizedIntensity
                    }
                }
            }
        }
        
        do {
            try audioEngine.start()
        } catch {
            appState.log("⚠️ Audio Engine failed to start: \(error.localizedDescription)")
        }
    }
    
    var onPlaybackFinished: (() -> Void)?
    
    private var scheduledBuffersCount: Int = 0
    private var isStreamFinished: Bool = false
    
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
        
        if !playerNode.isPlaying {
            playerNode.play()
        }
        
        DispatchQueue.main.async {
            self.scheduledBuffersCount += 1
        }
        
        playerNode.scheduleBuffer(buffer) { [weak self] in
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.scheduledBuffersCount -= 1
                
                if self.isStreamFinished && self.scheduledBuffersCount == 0 {
                    print("🔊 Audio playback fully finished.")
                    self.isStreamFinished = false // Reset for next interaction
                    self.onPlaybackFinished?()
                }
            }
        }
    }
    
    func finishStream() {
        DispatchQueue.main.async {
            self.isStreamFinished = true
            // In case there weren't any chunks successfully played, or they finished instantly
            if self.scheduledBuffersCount == 0 {
                print("⏹️ Stream finished and queue is empty.")
                self.isStreamFinished = false
                self.onPlaybackFinished?()
            }
        }
    }
    
    func stop() {
        playerNode.stop()
        audioEngine.stop()
        DispatchQueue.main.async {
            self.scheduledBuffersCount = 0
            self.isStreamFinished = false
        }
    }
}
