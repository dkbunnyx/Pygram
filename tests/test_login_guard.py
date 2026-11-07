
import json
import pytest

from src.core import login_guard


@pytest.fixture
def local_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(
        login_guard,
        "get_local_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(login_guard.time, "time", lambda: 1_000_000)
    return tmp_path


class TestLoginGuard:
    def test_first_two_failures_do_not_lock(self, local_guard):
        assert login_guard.record_failure("vasya") == 0
        assert login_guard.record_failure("vasya") == 0
        assert login_guard.get_lock_remaining("vasya") == 0

    @pytest.mark.parametrize(
        ("failures", "expected_lock"),
        [
            (3, 30),
            (4, 30),
            (5, 60),
            (9, 60),
            (10, 180),
            (15, 180),
        ],
    )
    def test_lock_thresholds(
        self, local_guard, monkeypatch, failures, expected_lock
    ):
        current_time = [1_000_000]

        monkeypatch.setattr(
            login_guard.time,
            "time",
            lambda: current_time[0],
        )

        for attempt in range(failures):
            result = login_guard.record_failure("vasya")

            # Перематываем время только между попытками,
            # но не после последней.
            if result and attempt < failures - 1:
                current_time[0] += result

        assert result == expected_lock
        assert login_guard.get_lock_remaining("vasya") == expected_lock


    def test_attempt_during_lock_does_not_increase_failures(
        self, local_guard
    ):
        for _ in range(3):
            login_guard.record_failure("vasya")

        assert login_guard.record_failure("vasya") == 30

        path = login_guard._state_path("vasya")
        state = json.loads(path.read_text(encoding="utf-8"))

        assert state["failures"] == 3

    def test_lock_expires(self, local_guard, monkeypatch):
        for _ in range(3):
            login_guard.record_failure("vasya")

        monkeypatch.setattr(
            login_guard.time,
            "time",
            lambda: 1_000_031,
        )

        assert login_guard.get_lock_remaining("vasya") == 0

    def test_success_resets_attempts(self, local_guard):
        for _ in range(3):
            login_guard.record_failure("vasya")

        login_guard.reset_attempts("vasya")

        assert login_guard.get_lock_remaining("vasya") == 0
        assert login_guard.record_failure("vasya") == 0

    def test_accounts_have_separate_counters(self, local_guard):
        for _ in range(3):
            login_guard.record_failure("vasya")

        assert login_guard.get_lock_remaining("vasya") == 30
        assert login_guard.get_lock_remaining("petya") == 0

    def test_corrupted_state_starts_from_zero(self, local_guard):
        path = login_guard._state_path("vasya")
        path.write_text("{broken json", encoding="utf-8")

        assert login_guard.record_failure("vasya") == 0
