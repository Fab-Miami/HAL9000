import Foundation
import Combine

enum AppStateStatus {
    case idle
    case listening
    case processing
}

class AppState: ObservableObject {
    @Published var status: AppStateStatus = .idle
    @Published var intensity: Double = 0.0
    @Published var isConversationActive: Bool = false
    
    func log(_ message: String) {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss.SSS"
        let timestamp = formatter.string(from: Date())
        let logMessage = "[\(timestamp)] \(message)"
        
        DispatchQueue.main.async {
            print(logMessage)
        }
    }
}
