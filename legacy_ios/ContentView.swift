import SwiftUI

struct ContentView: View {
    @ObservedObject var appState: AppState
    
    // For the slow pulse in LISTENING mode
    @State private var isPulsing = false
    // For the ocular core in THINKING mode
    @State private var orangePulse = false
    
    var body: some View {
        // Center the entire graphism in the screen
        ZStack {
            Color(hex: "0f1415").edgesIgnoringSafeArea(.all)
            
            // Static Background Image (The Hardware) LOCAL
            Image("HAL")
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: 350, height: 350)

            // Pulsing Inner Glow (The Intelligence)
            Circle()
                .fill(
                    RadialGradient(
                        gradient: Gradient(colors: [.red, Color.red.opacity(0.5), .clear]),
                        center: .center,
                        startRadius: 6,
                        endRadius: 96
                    )
                )
                .frame(width: 216, height: 216)
                .scaleEffect(currentScale)
                .opacity(currentOpacity)
                .blur(radius: 2)
                .blendMode(.screen) // Cinematic additive glow
                .animation(.interactiveSpring(response: 0.15, dampingFraction: 0.8), value: appState.intensity)
                .animation(.interactiveSpring(response: 0.3, dampingFraction: 0.8), value: appState.status)
                .onChange(of: appState.status) { newStatus in
                    if newStatus == .listening {
                        withAnimation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true)) {
                            isPulsing = true
                        }
                    } else if newStatus == .thinking {
                        withAnimation(.easeInOut(duration: 0.6).repeatForever(autoreverses: true)) {
                            orangePulse = true
                        }
                    } else {
                        withAnimation(.easeInOut(duration: 0.5)) {
                            isPulsing = false
                            orangePulse = false
                        }
                    }
                }
            
            // The Ocular Core (The "Thinking" Dot)
            Circle()
                .fill(Color(hex: "f4f846"))
                .frame(width: 8, height: 8)
                .blur(radius: 0.5)
                .scaleEffect(appState.status == .thinking ? (orangePulse ? 1.5 : 1.0) : 0.5)
                .opacity(appState.status == .thinking ? 1.0 : 0.0)
                .blendMode(.plusLighter) // Makes it pop against the red
                .animation(.easeInOut(duration: 0.6).repeatForever(autoreverses: true), value: orangePulse)
                .animation(.easeInOut(duration: 0.3), value: appState.status)
        }
        .contentShape(Rectangle()) // Make the whole ZStack tappable
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    if !appState.isScreenPressed {
                        appState.isScreenPressed = true
                        HapticManager.shared.triggerHeavy()
                        appState.log("🖐️ Screen pressed")
                    }
                }
                .onEnded { _ in
                    appState.isScreenPressed = false
                    appState.log("🖐️ Screen released")
                }
        )
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear {
            if appState.status == .listening {
                withAnimation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true)) {
                    isPulsing = true
                }
            }
        }
    }
    
    private var currentScale: CGFloat {
        if appState.status == .idle {
            // Nothing is happening => no animation (rest at 0.9)
            return 0.9
        } else if (appState.status == .listening || appState.status == .thinking) && appState.intensity < 0.05 {
            // HAL is waiting or thinking => slow pulsating state
            return isPulsing ? 1.0 : 0.9
        } else {
            // User or HAL is talking => reacting to volume
            // Note: During .processing (HAL talking), intensity is artificially scaled x1.5 in AudioPlayerManager
            return 0.9 + (appState.intensity * 0.48)
        }
    }
    
    private var currentOpacity: Double {
        if appState.status == .idle {
            return 0.4
        } else if (appState.status == .listening || appState.status == .thinking) && appState.intensity < 0.05 {
            return isPulsing ? 0.6 : 0.4
        } else {
            return 0.4 + (appState.intensity * 0.6)
        }
    }
}
