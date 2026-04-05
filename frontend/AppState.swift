import Foundation
import Combine

enum AppStateStatus {
    case idle
    case listening
    case processing
}

class AppState: ObservableObject {
    @Published var status: AppStateStatus = .idle
    @Published var debugLogs: [String] = []
    
    func log(_ message: String) {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss.SSS"
        let timestamp = formatter.string(from: Date())
        let logMessage = "[\(timestamp)] \(message)"
        
        DispatchQueue.main.async {
            self.debugLogs.append(logMessage)
            print(logMessage)
        }
    }
}
