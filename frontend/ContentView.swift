import SwiftUI

struct ContentView: View {
    @ObservedObject var appState: AppState
    
    var body: some View {
        VStack(spacing: 0) {
            // Top half: Status Circle
            ZStack {
                Color.black.edgesIgnoringSafeArea(.all)
                
                Circle()
                    .fill(Color.red)
                    .frame(width: appState.status == .idle ? 50 : 150,
                           height: appState.status == .idle ? 50 : 150)
                    .opacity(appState.status == .idle ? 0.3 : 1.0)
                    .shadow(color: .red, radius: appState.status == .idle ? 0 : 20)
                    .animation(
                        appState.status == .listening 
                            ? Animation.easeInOut(duration: 0.8).repeatForever(autoreverses: true) 
                            : .default,
                        value: appState.status
                    )
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            
            // Bottom half: Debug Logs
            ScrollView {
                ScrollViewReader { proxy in
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(Array(appState.debugLogs.enumerated()), id: \.offset) { index, log in
                            Text(log)
                                .font(.system(size: 12, design: .monospaced))
                                .foregroundColor(.green)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .id(index)
                        }
                    }
                    .padding()
                    .onChange(of: appState.debugLogs.count) { _ in
                        if !appState.debugLogs.isEmpty {
                            withAnimation {
                                proxy.scrollTo(appState.debugLogs.count - 1, anchor: .bottom)
                            }
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(UIColor.darkGray))
        }
    }
}
