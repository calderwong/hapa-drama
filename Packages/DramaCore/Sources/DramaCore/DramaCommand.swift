import Foundation

public struct DramaCommand: Codable, Equatable, Sendable {
    public var apiVersion: String
    public var commandId: String
    public var actor: String
    public var kind: String
    public var mode: String
    public var payload: [String: String]

    public init(apiVersion: String = "v1", commandId: String, actor: String, kind: String, mode: String, payload: [String: String] = [:]) {
        self.apiVersion = apiVersion
        self.commandId = commandId
        self.actor = actor
        self.kind = kind
        self.mode = mode
        self.payload = payload
    }
}

public actor DramaCore {
    public init() {}

    public func dispatch(_ command: DramaCommand) -> [String] {
        ["command.accepted", "engine.selected", "generation.started"]
    }
}
