from roam_approve_bridge.models import ApprovalRequestCreate, Decision
from roam_approve_bridge.store import AlreadyResolvedError, ApprovalStore, NotFoundError


def request_create(timeout_s=300):
    return ApprovalRequestCreate(
        agent="devin-cli",
        session_id="session-1",
        title="Run command",
        lines=["make test"],
        timeout_s=timeout_s,
    )


def test_resolution_callback_runs_once(clock):
    resolved = []
    store = ApprovalStore(clock=clock, on_resolved=resolved.append)
    request = store.add(request_create())
    store.decide(request.id, Decision(decision="approve"))
    clock.advance(request.timeout_s + 1)
    assert store.expire_due() == 0
    assert resolved == [request]


def test_resolution_callback_exception_does_not_propagate(clock):
    def fail(_request):
        raise RuntimeError("callback failure")

    store = ApprovalStore(clock=clock, on_resolved=fail)
    request = store.add(request_create())
    resolved = store.decide(request.id, Decision(decision="approve"))
    assert resolved.status == "approved"


def test_lazy_expiry_and_conflict(clock):
    store = ApprovalStore(clock=clock)
    request = store.add(request_create(timeout_s=1))
    clock.advance(2)
    assert store.get(request.id).status == "expired"
    try:
        store.decide(request.id, Decision(decision="approve"))
    except AlreadyResolvedError:
        pass
    else:
        raise AssertionError("resolved request accepted a new decision")


def test_resolved_requests_are_purged_after_retention(clock):
    store = ApprovalStore(clock=clock, retention_s=60)
    done = store.add(request_create())
    pending = store.add(request_create())
    store.decide(done.id, Decision(decision="approve"))
    clock.advance(59)
    store.expire_due()
    assert store.get(done.id).status == "approved"
    clock.advance(1)
    store.expire_due()
    try:
        store.get(done.id)
    except NotFoundError:
        pass
    else:
        raise AssertionError("resolved request was not purged")
    assert store.is_pending(str(pending.id))


def test_unknown_request_raises_not_found(clock):
    from uuid import uuid4

    store = ApprovalStore(clock=clock)
    try:
        store.get(uuid4())
    except NotFoundError:
        pass
    else:
        raise AssertionError("unknown request was returned")
