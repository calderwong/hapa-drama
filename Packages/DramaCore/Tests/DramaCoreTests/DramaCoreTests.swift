import XCTest
@testable import DramaCore

final class DramaCoreTests: XCTestCase {
    func testDispatchStartsWithAcceptedEvent() async {
        let core = DramaCore()
        let command = DramaCommand(commandId: "test", actor: "test", kind: "synthesize", mode: "flow")
        let events = await core.dispatch(command)
        XCTAssertEqual(events.first, "command.accepted")
    }
}
