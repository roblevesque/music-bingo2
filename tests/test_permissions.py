from app.services.permissions import (
    MIN_PASSWORD_LENGTH, USERNAME_RE, Account, generate_password, leaves_an_admin,
)


def test_generated_passwords_are_long_varied_and_unambiguous():
    seen = {generate_password() for _ in range(200)}
    assert len(seen) == 200
    for password in seen:
        assert len(password) >= MIN_PASSWORD_LENGTH
        assert any(c.islower() for c in password) and any(c.isupper() for c in password) and any(c.isdigit() for c in password)
        assert not set(password) & set("l1O0I")


def test_username_rules():
    for good in ("host", "dj.mike", "a_b-c", "abc", "x" * 32):
        assert USERNAME_RE.match(good), good
    for bad in ("ab", "x" * 33, "Has Space", "UPPER", "semi;colon", "", "name\n"):
        assert not USERNAME_RE.match(bad), bad


def accounts(*specs):
    return [Account(i, admin, active) for i, (admin, active) in enumerate(specs, start=1)]


def test_the_last_admin_cannot_demote_or_disable_themselves():
    only = accounts((True, True), (False, True))
    assert not leaves_an_admin(only, 1, is_admin=False, is_active=True)   # demote
    assert not leaves_an_admin(only, 1, is_admin=True, is_active=False)   # disable
    assert leaves_an_admin(only, 1, is_admin=True, is_active=True)        # no change is fine
    assert leaves_an_admin(only, 2, is_admin=False, is_active=False)      # disabling a non-admin is fine


def test_another_active_admin_makes_changes_safe():
    two = accounts((True, True), (True, True))
    assert leaves_an_admin(two, 1, is_admin=False, is_active=True)
    assert leaves_an_admin(two, 2, is_admin=True, is_active=False)


def test_a_disabled_admin_does_not_count():
    mixed = accounts((True, True), (True, False))
    assert not leaves_an_admin(mixed, 1, is_admin=False, is_active=True)  # the other admin is disabled
    assert leaves_an_admin(mixed, 2, is_admin=True, is_active=True)       # re-enabling them is fine
