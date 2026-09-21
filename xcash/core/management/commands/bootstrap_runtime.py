"""在一个 Django 进程中按顺序准备运行状态，任一步失败即阻止服务启动。"""

import time

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "执行数据库迁移并初始化运行所需的基础数据和管理员"

    def add_arguments(self, parser):
        parser.add_argument("--skip-migrations", action="store_true")

    def handle(self, *args, **options):
        # 升级脚本单独执行 migrate，以区分迁移中失败与迁移后的初始化失败。
        # 普通 docker compose up 仍走完整初始化，不能依赖宿主机上的升级标记。
        commands = (
            [] if options["skip_migrations"] else [("migrate", {"interactive": False})]
        )
        commands += [
            ("ensure_default_reference_data", {}),
            ("ensure_default_superuser", {}),
        ]
        for name, kwargs in commands:
            started = time.monotonic()
            self.stdout.write(f"[bootstrap] {name} started")
            self.stdout.flush()
            call_command(name, stdout=self.stdout, stderr=self.stderr, **kwargs)
            self.stdout.write(
                f"[bootstrap] {name} completed in {time.monotonic() - started:.1f}s"
            )
            self.stdout.flush()
