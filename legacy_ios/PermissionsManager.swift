import Foundation
import AVFoundation
import Speech

class PermissionsManager {
    static let shared = PermissionsManager()
    
    private init() {}
    
    func requestMicrophonePermission(completion: @escaping (Bool) -> Void) {
        let currentStatus = AVAudioSession.sharedInstance().recordPermission
        switch currentStatus {
        case .granted:
            completion(true)
        case .denied:
            completion(false)
        case .undetermined:
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                DispatchQueue.main.async {
                    completion(granted)
                }
            }
        @unknown default:
            completion(false)
        }
    }
    
    func requestSpeechRecognitionPermission(completion: @escaping (Bool) -> Void) {
        SFSpeechRecognizer.requestAuthorization { status in
            DispatchQueue.main.async {
                switch status {
                case .authorized:
                    completion(true)
                default:
                    completion(false)
                }
            }
        }
    }
}

