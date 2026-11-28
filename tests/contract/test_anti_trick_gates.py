"""MeetingConverter's architecture inventory and ratchet baseline."""

from tools.meeting_quality import inspect, regressions


def test_anti_trick_gates_cover_the_owner_source():
    findings, omissions = regressions(inspect())
    assert not omissions, omissions
    assert not findings, findings
