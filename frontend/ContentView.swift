import SwiftUI

struct ContentView: View {
    @ObservedObject var appState: AppState
    
    var body: some View {
        VStack(spacing: 0) {
            // Top half: HAL 9000 Eye (Layered Animation)
            ZStack {
                Color.black.edgesIgnoringSafeArea(.all)
                
                // Static Background Image (The Hardware)
                AsyncImage(url: URL(string: "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f6/HAL9000.svg/1280px-HAL9000.svg.png")) { image in
                    image
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: 300, height: 300)
                } placeholder: {
                    Circle()
                        .fill(Color.gray.opacity(0.1))
                        .frame(width: 300, height: 300)
                }
                
                // Pulsing Inner Glow (The Intelligence)
                // This layer reacts to audio intensity without moving the frame.
                Circle()
                    .fill(
                        RadialGradient(
                            gradient: Gradient(colors: [.red, Color.red.opacity(0.3), .clear]),
                            center: .center,
                            startRadius: 5,
                            endRadius: 60
                        )
                    )
                    .frame(width: 140, height: 140)
                    .scaleEffect(0.8 + (appState.intensity * 0.5))
                    .opacity(0.3 + (appState.intensity * 0.7))
                    .blur(radius: 2)
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
