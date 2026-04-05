import SwiftUI

struct ContentView: View {
    @ObservedObject var appState: AppState
    
    var body: some View {
        VStack(spacing: 0) {
            // Top half: HAL 9000 Eye (Layered Animation)
            ZStack {
                Color.black.edgesIgnoringSafeArea(.all)
                
                // Static Background Image (The Hardware) LOCAL
                Image("HAL")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 350, height: 350)

                
                // Pulsing Inner Glow (The Intelligence)
                // This layer reacts to audio intensity without moving the frame.
                Circle()
                    .fill(
                        RadialGradient(
                            gradient: Gradient(colors: [.red, Color.red.opacity(0.5), .clear]),
                            center: .center,
                            startRadius: 5,
                            endRadius: 80
                        )
                    )
                    .frame(width: 180, height: 180)
                    // Baseline of 0.2 means it's never fully "dead"
                    .scaleEffect(0.9 + (appState.intensity * 0.4))
                    .opacity(0.4 + (appState.intensity * 0.6))
                    .blur(radius: 2)
                    .blendMode(.screen) // Cinematic additive glow
                    .animation(.interactiveSpring(response: 0.15, dampingFraction: 0.8), value: appState.intensity)
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
