"""首次部署和升级共享初始化顺序，失败不能继续执行后续步骤。"""

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.management.commands.bootstrap_runtime import Command

MODULE = "core.management.commands.bootstrap_runtime"


@pytest.mark.parametrize("skip_migrations", [False, True])
def test_bootstrap_preserves_required_order(skip_migrations):
    with patch(f"{MODULE}.call_command") as run:
        call_command("bootstrap_runtime", skip_migrations=skip_migrations)
    expected = ["ensure_default_reference_data", "ensure_default_superuser"]
    if not skip_migrations:
        expected.insert(0, "migrate")
        assert run.call_args_list[0].kwargs["interactive"] is False
    assert [call.args[0] for call in run.call_args_list] == expected


@pytest.mark.parametrize(
    "failure", ["migrate", "ensure_default_reference_data", "ensure_default_superuser"]
)
def test_bootstrap_failure_stops_later_steps(failure):
    def execute(name, **kwargs):
        if name == failure:
            raise CommandError("initialization failed")

    with (
        patch(f"{MODULE}.call_command", side_effect=execute) as run,
        pytest.raises(CommandError, match="initialization failed") as error,
    ):
        call_command("bootstrap_runtime")
    assert run.call_args.args[0] == failure
    assert error.value.returncode == (1 if failure == "migrate" else 20)


@pytest.mark.parametrize("failure", ["migrate", "ensure_default_reference_data"])
def test_cli_exit_code_distinguishes_migration_and_setup_failure(failure):
    def execute(name, **kwargs):
        if name == failure:
            # 即使迁移内部错误自己带了 20，也必须被归一为迁移失败。
            raise CommandError("command failed", returncode=20)

    command = Command(stdout=StringIO(), stderr=StringIO())
    with (
        patch(f"{MODULE}.call_command", side_effect=execute),
        pytest.raises(SystemExit) as error,
    ):
        command.run_from_argv(["manage.py", "bootstrap_runtime", "--skip-checks"])
    assert error.value.code == (1 if failure == "migrate" else 20)


def test_interrupted_setup_is_not_reported_as_recoverable():
    with (
        patch(f"{MODULE}.call_command", side_effect=[None, KeyboardInterrupt]),
        pytest.raises(KeyboardInterrupt),
    ):
        call_command("bootstrap_runtime")
