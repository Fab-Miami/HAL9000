import Foundation
import AVFoundation

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
}
