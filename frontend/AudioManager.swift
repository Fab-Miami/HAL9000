import Foundation
import AVFoundation

class AudioManager {
    private let audioEngine = AVAudioEngine()
    private let appState: AppState
    
    private var isRecording = false
    private var firstChunkLogged = false
    
    private var audioConverter: AVAudioConverter?
    private var outputFormat: AVAudioFormat?
    
    // Callback to emit raw Data when tapped
    var onAudioDataAvailable: ((Data) -> Void)?
    
    init(appState: AppState) {
        self.appState = appState
        setupAudioFormat()
    }
    
    private func setupAudioFormat() {
        // Preferred 16kHz, mono, 16-bit PCM for server/AI processing
        guard let format = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: false) else {
            appState.log("AudioManager: Failed to create 16kHz mono format.")
            return
        }
        self.outputFormat = format
    }
    
    func startTapping() {
        guard !isRecording else { return }
        
        let inputNode = audioEngine.inputNode
        let inputFormat = inputNode.outputFormat(forBus: 0)
        
        guard let outputFormat = self.outputFormat else {
            appState.log("AudioManager: Missing output format.")
            return
        }
        
        // Initialize the converter
        audioConverter = AVAudioConverter(from: inputFormat, to: outputFormat)
        
        // Install tap
        inputNode.installTap(onBus: 0, bufferSize: 2048, format: inputFormat) { [weak self] (buffer, time) in
            guard let self = self else { return }
            
            // Calculate real-time intensity (RMS) for UI pulsing
            if let channelData = buffer.floatChannelData?[0] {
                let frameLength = Int(buffer.frameLength)
                var sum: Float = 0
                for i in 0..<frameLength {
                    sum += channelData[i] * channelData[i]
                }
                let rms = sqrt(sum / Float(frameLength))
                let normalizedIntensity = Double(min(max(rms * 5.0, 0.0), 1.0))
                
                Task { @MainActor in
                    self.appState.intensity = normalizedIntensity
                }
            }
            
            self.processAudioBuffer(buffer)
        }

        
        audioEngine.prepare()
        
        do {
            try audioEngine.start()
            isRecording = true
            firstChunkLogged = false
            appState.log("AudioManager: Microphone tap started (16kHz Mono).")
        } catch {
            appState.log("AudioManager: Engine failed to start - \(error.localizedDescription)")
        }
    }
    
    func stopTapping() {
        guard isRecording else { return }
        
        audioEngine.inputNode.removeTap(onBus: 0)
        audioEngine.stop()
        isRecording = false
        appState.log("AudioManager: Microphone tap stopped.")
    }
    
    private func processAudioBuffer(_ buffer: AVAudioPCMBuffer) {
        guard let audioConverter = audioConverter, let outputFormat = outputFormat else { return }
        
        // Calculate the capacity required for the output buffer
        let inputSampleRate = buffer.format.sampleRate
        let outputSampleRate = outputFormat.sampleRate
        guard inputSampleRate > 0 else { return }
        
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * (outputSampleRate / inputSampleRate))
        guard let convertedBuffer = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: capacity) else { return }
        
        var error: NSError? = nil
        var allPassed = false
        
        // Perform the conversion
        let status = audioConverter.convert(to: convertedBuffer, error: &error) { packetCount, outStatus in
            if !allPassed {
                allPassed = true
                outStatus.pointee = .haveData
                return buffer
            }
            outStatus.pointee = .noDataNow
            return nil
        }
        
        if status == .error || error != nil {
            print("Audio conversion error")
            return
        }
        
        // Convert to raw Data
        let audioBufferList = convertedBuffer.audioBufferList.pointee.mBuffers
        let dataSize = Int(audioBufferList.mDataByteSize)
        guard let dataPointer = audioBufferList.mData, dataSize > 0 else { return }
        
        let data = Data(bytes: dataPointer, count: dataSize)
        
        // Throttle log spam: Only log the first chunk
        if !firstChunkLogged {
            DispatchQueue.main.async { [weak self] in
                self?.appState.log("AudioManager: First raw audio chunk sent (\(dataSize) bytes).")
            }
            firstChunkLogged = true
        }
        
        // Pass data to the core logic
        onAudioDataAvailable?(data)
    }
}
