import SwiftUI

@main
struct HapaDramaApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .windowStyle(.hiddenTitleBar)
    }
}

enum DramaMode: String, CaseIterable, Identifiable {
    case browse = "Browse"
    case forge = "Forge"
    case navigate = "Navigate"
    case compose = "Compose"

    var id: String { rawValue }
}

struct ContentView: View {
    @State private var mode: DramaMode = .forge
    @State private var script: String = "Hapa Drama is online."
    @State private var directorLog: [String] = ["Ready."]

    var body: some View {
        ZStack {
            LinearGradient(colors: [Color.black, Color(red: 0.03, green: 0.07, blue: 0.14)], startPoint: .topLeading, endPoint: .bottomTrailing)
                .ignoresSafeArea()
            VStack(alignment: .leading, spacing: 18) {
                header
                Picker("Mode", selection: $mode) {
                    ForEach(DramaMode.allCases) { mode in
                        Text(mode.rawValue).tag(mode)
                    }
                }
                .pickerStyle(.segmented)
                HStack(alignment: .top, spacing: 18) {
                    primaryPanel
                    directorTrack
                }
                Spacer()
            }
            .padding(28)
        }
        .foregroundStyle(.white)
        .frame(minWidth: 980, minHeight: 680)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(".hapaDrama")
                .font(.caption)
                .foregroundStyle(.cyan)
                .tracking(3)
            Text("Hapa Voice Synthesis Node")
                .font(.system(size: 46, weight: .bold, design: .rounded))
            Text("Browse voices. Forge scripts. Navigate waveforms. Compose Cymatica layers.")
                .foregroundStyle(.white.opacity(0.72))
        }
    }

    private var primaryPanel: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(mode.rawValue)
                .font(.title2.bold())
            if mode == .forge || mode == .compose {
                TextEditor(text: $script)
                    .font(.system(.body, design: .monospaced))
                    .scrollContentBackground(.hidden)
                    .frame(minHeight: 260)
                    .padding(10)
                    .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: 18))
                Button("Generate via Hapa Drama API") {
                    directorLog.insert("Submit command through /v1/commands with shared schema.", at: 0)
                }
                .buttonStyle(.borderedProminent)
            } else if mode == .browse {
                Text("Voice library grid placeholder. Cultivator entanglement levels will render here.")
                    .foregroundStyle(.white.opacity(0.72))
            } else {
                Text("Waveform inspector placeholder. Generation lineage and provenance will render here.")
                    .foregroundStyle(.white.opacity(0.72))
            }
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Color.white.opacity(0.07), in: RoundedRectangle(cornerRadius: 24))
    }

    private var directorTrack: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Director Track")
                .font(.title2.bold())
            ForEach(directorLog.indices, id: \.self) { index in
                Text(directorLog[index])
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.78))
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.cyan.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
            }
        }
        .padding(20)
        .frame(width: 320, alignment: .topLeading)
        .background(Color.white.opacity(0.07), in: RoundedRectangle(cornerRadius: 24))
    }
}
