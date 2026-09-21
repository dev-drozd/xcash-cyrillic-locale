"""在一个 Django 进程中按顺序准备运行状态，任一步失败即阻止服务启动。"""

import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

# upgrade.sh 的阶段协议：仅在 migrate（含 post_migrate）完整返回后，初始化失败才
# 返回 20。迁移失败或进程被终止仍返回普通非零状态，脚本必须按迁移状态未知处理。
SETUP_FAILURE_EXIT_CODE = 20


class Command(BaseCommand):
    help = "执行数据库迁移并初始化运行所需的基础数据和管理员"

    def add_arguments(self, parser):
        parser.add_argument("--skip-migrations", action="store_true")

    def handle(self, *args, **options):
        if not options["skip_migrations"]:
            try:
                self.run_step("migrate", interactive=False)
            except CommandError as exc:
                # 子命令自定义的退出码不得冒充“迁移完成”，统一按迁移失败退出。
                raise CommandError(str(exc)) from exc
        # 仅已知迁移完成的失败恢复路径使用 --skip-migrations；正常升级和首次部署
        # 均在同一进程运行三个步骤，不省略空迁移计划下的 post_migrate 触发器维护。
        try:
            self.run_step("ensure_default_reference_data")
            self.run_step("ensure_default_superuser")
        except Exception as exc:
            raise CommandError(
                f"runtime initialization failed after migrations: {exc}",
                returncode=SETUP_FAILURE_EXIT_CODE,
            ) from exc

    def run_step(self, name, **kwargs):
        started = time.monotonic()
        self.stdout.write(f"[bootstrap] {name} started")
        self.stdout.flush()
        call_command(name, stdout=self.stdout, stderr=self.stderr, **kwargs)
        self.stdout.write(
            f"[bootstrap] {name} completed in {time.monotonic() - started:.1f}s"
        )
        self.stdout.flush()
