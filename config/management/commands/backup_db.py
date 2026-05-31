"""Snapshot the dev database into ./backups/.

For SQLite, uses the online backup API (sqlite3.Connection.backup) so we
can copy a live database without locking it for long. For other engines,
fall back to manage.py dumpdata (slower but engine-agnostic).
"""
import os
import shutil
import sqlite3
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Сделать снимок базы в backups/<engine>-<timestamp>.<ext>'

    def add_arguments(self, parser):
        parser.add_argument(
            '--keep', type=int, default=10,
            help='Сколько последних бэкапов хранить (по умолчанию 10).',
        )
        parser.add_argument(
            '--out-dir', default=None,
            help='Куда складывать бэкапы (по умолчанию: BASE_DIR/backups).',
        )

    def handle(self, *args, keep, out_dir, **opts):
        base_dir = Path(settings.BASE_DIR)
        out = Path(out_dir) if out_dir else base_dir / 'backups'
        out.mkdir(parents=True, exist_ok=True)

        engine = settings.DATABASES['default']['ENGINE']
        ts = time.strftime('%Y%m%d-%H%M%S')

        if 'sqlite' in engine:
            src = Path(settings.DATABASES['default']['NAME'])
            dst = out / f'sqlite-{ts}.sqlite3'
            self._backup_sqlite(src, dst)
        else:
            dst = out / f'dump-{ts}.json'
            from django.core.management import call_command
            with dst.open('w', encoding='utf-8') as fh:
                call_command(
                    'dumpdata',
                    '--natural-foreign', '--natural-primary',
                    exclude=['contenttypes', 'auth.Permission'],
                    stdout=fh,
                )

        size_kb = dst.stat().st_size / 1024
        self.stdout.write(self.style.SUCCESS(
            f'Бэкап: {dst.relative_to(base_dir)}  ({size_kb:.1f} KB)'
        ))

        self._rotate(out, keep)

    def _backup_sqlite(self, src: Path, dst: Path) -> None:
        if not src.exists():
            raise FileNotFoundError(f'{src} not found')
        # online backup — safe even with active writers
        with sqlite3.connect(src) as src_con, sqlite3.connect(dst) as dst_con:
            src_con.backup(dst_con)

    def _rotate(self, out: Path, keep: int) -> None:
        files = sorted(
            (p for p in out.iterdir()
             if p.is_file() and (p.name.startswith('sqlite-')
                                 or p.name.startswith('dump-'))),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in files[keep:]:
            try:
                old.unlink()
                self.stdout.write(f'  ротация: удалён {old.name}')
            except OSError as e:
                self.stderr.write(f'  не удалось удалить {old.name}: {e}')
