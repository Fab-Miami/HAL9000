import Foundation
import UIKit

class WebSocketManager: NSObject, URLSessionWebSocketDelegate {
    private var webSocketTask: URLSessionWebSocketTask?
    private let appState: AppState
    private var session: URLSession?
    
    var onAudioReceived: ((Data) -> Void)?
    var onStringReceived: ((String) -> Void)?
    
    init(appState: AppState) {
        self.appState = appState
        super.init()
        
        // Use a custom session to handle SSL certificate bypass
        let configuration = URLSessionConfiguration.default
        self.session = URLSession(configuration: configuration, delegate: self, delegateQueue: .main)
    }
    
    func connect() {
        guard webSocketTask == nil else {
            appState.log("ℹ️ WebSocket is already connected or connecting.")
            return
        }
        
        // Connect to remote server on dedicated port 8001
        let deviceId = UIDevice.current.identifierForVendor?.uuidString ?? "unknown_device"
        guard let url = URL(string: "ws://159.223.167.180:8001/ws/hal/\(deviceId)/") else {
            appState.log("❌ Invalid WebSocket URL.")
            return
        }
        
        guard let session = session else { return }
        webSocketTask = session.webSocketTask(with: url)
        webSocketTask?.resume()
        appState.log("🔌 WebSocket connecting to \(url.absoluteString)...")
        
        receiveMessage()
    }
    
    func disconnect() {
        webSocketTask?.cancel(with: .normalClosure, reason: nil)
        webSocketTask = nil
        appState.log("🔴 WebSocket disconnected.")
    }
    
    func send(data: Data) {
        guard let webSocketTask = webSocketTask else { return }
        
        let message = URLSessionWebSocketTask.Message.data(data)
        webSocketTask.send(message) { error in
            if let error = error as NSError? {
                if error.domain == NSURLErrorDomain && error.code == NSURLErrorCancelled {
                    return // Ignore cancelled error on disconnect
                }
                print("⚠️ WebSocket send error: \(error.localizedDescription)")
            }
        }
    }
    
    private func receiveMessage() {
        webSocketTask?.receive { [weak self] result in
            guard let self = self else { return }
            
            switch result {
            case .success(let message):
                switch message {
                case .data(let data):
                    print("⬇️ Received data: \(data.count) bytes")
                    self.onAudioReceived?(data)
                case .string(let text):
                    print("⬇️ Received string: \(text)")
                    self.onStringReceived?(text)
                @unknown default:
                    break
                }
                
                // Continue listening
                self.receiveMessage()
                
            case .failure(let error):
                print("⚠️ WebSocket receive error: \(error.localizedDescription)")
                self.webSocketTask = nil
            }
        }
    }
    
    // MARK: - URLSessionDelegate
    
    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge, completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        
        // For development: Skip SSL validation for the specific IP
        if challenge.protectionSpace.host == "159.223.167.180" {
            appState.log("🔓 Bypassing SSL validation for 159.223.167.180...")
            completionHandler(.useCredential, URLCredential(trust: challenge.protectionSpace.serverTrust!))
        } else {
            completionHandler(.performDefaultHandling, nil)
        }
    }
}
