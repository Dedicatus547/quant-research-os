import pytest
from ci.apparmor.runtime_guard import PROFILE, ZERO_CAPS, require_isolated, require_label


def test_kernel_label_requires_the_exact_expected_profile_and_mode():
    require_label("unconfined\n", "unconfined")
    require_label(f"{PROFILE} (unconfined)\n", PROFILE)
    for raw in ("unconfined", f"{PROFILE} (enforce)", f"other//{PROFILE} (unconfined)"):
        with pytest.raises(RuntimeError):
            require_label(raw, PROFILE)
    with pytest.raises(RuntimeError):
        require_label(f"{PROFILE} (unconfined)", "unconfined")


@pytest.mark.parametrize("field", [*ZERO_CAPS, "NoNewPrivs", "user", "net", "pid"])
def test_existing_isolation_predicates_cannot_be_waived(field):
    caps = {key: "0000000000000000" for key in ZERO_CAPS}
    caps["NoNewPrivs"] = "1"
    current, parent = ["user:new", "net:new", "pid:new"], ["user:old", "net:old", "pid:old"]
    require_isolated(current, parent, caps)
    if field in ZERO_CAPS:
        caps[field] = "0000000000000001"
    elif field == "NoNewPrivs":
        caps[field] = "0"
    else:
        index = ["user", "net", "pid"].index(field)
        current[index] = parent[index]
    with pytest.raises(RuntimeError):
        require_isolated(current, parent, caps)
