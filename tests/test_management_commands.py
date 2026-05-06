"""Smoke tests for management commands."""
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import Movement, Rental, RentalItem


def test_mark_overdue_flips_only_qualifying_rentals(admin_user, customer, product):
    today = timezone.localdate()
    # Past due, has outstanding → should be flipped
    r1 = Rental.objects.create(
        customer=customer, due_date=today - timedelta(days=1),
        created_by=admin_user, status=Rental.Status.ACTIVE,
    )
    item = RentalItem.objects.create(
        rental=r1, product=product, qty=3, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=3, created_by=admin_user,
    )
    # Past due, fully returned → should NOT be flipped
    r2 = Rental.objects.create(
        customer=customer, due_date=today - timedelta(days=1),
        created_by=admin_user, status=Rental.Status.ACTIVE,
    )
    item2 = RentalItem.objects.create(
        rental=r2, product=product, qty=2, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item2, kind=Movement.Kind.ISSUE, qty=2, created_by=admin_user,
    )
    Movement.objects.create(
        rental_item=item2, kind=Movement.Kind.RETURN, qty=2, created_by=admin_user,
    )
    # Future due → should NOT be flipped
    r3 = Rental.objects.create(
        customer=customer, due_date=today + timedelta(days=2),
        created_by=admin_user, status=Rental.Status.ACTIVE,
    )

    out = StringIO()
    call_command('mark_overdue', stdout=out)

    r1.refresh_from_db(); r2.refresh_from_db(); r3.refresh_from_db()
    assert r1.status == Rental.Status.OVERDUE
    assert r2.status == Rental.Status.ACTIVE
    assert r3.status == Rental.Status.ACTIVE


def test_mark_overdue_dry_run_doesnt_modify(admin_user, customer, product):
    rental = Rental.objects.create(
        customer=customer,
        due_date=timezone.localdate() - timedelta(days=2),
        created_by=admin_user,
        status=Rental.Status.ACTIVE,
    )
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=1, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=1, created_by=admin_user,
    )

    out = StringIO()
    call_command('mark_overdue', '--dry-run', stdout=out)
    rental.refresh_from_db()
    assert rental.status == Rental.Status.ACTIVE
    assert 'dry-run' in out.getvalue()


def test_backup_db_sqlite_helper_copies_db(tmp_path):
    """Hit the SQLite online-backup path directly with a real source file."""
    from core.management.commands.backup_db import Command
    import sqlite3

    src = tmp_path / 'src.sqlite3'
    with sqlite3.connect(src) as conn:
        conn.execute('CREATE TABLE t (x INT)')
        conn.execute('INSERT INTO t VALUES (1), (2), (3)')
        conn.commit()

    dst = tmp_path / 'dst.sqlite3'
    Command()._backup_sqlite(src, dst)

    assert dst.exists() and dst.stat().st_size > 0
    with sqlite3.connect(dst) as conn:
        rows = conn.execute('SELECT x FROM t ORDER BY x').fetchall()
    assert rows == [(1,), (2,), (3,)]


def test_backup_db_rotates_old_backups(tmp_path):
    """Rotation logic on its own — no DB needed."""
    from core.management.commands.backup_db import Command

    for i in range(4):
        f = tmp_path / f'sqlite-{i}.sqlite3'
        f.write_bytes(b'\x00' * 10)
        # ensure deterministic mtime ordering
        import os, time
        os.utime(f, (time.time() + i, time.time() + i))

    Command()._rotate(tmp_path, keep=2)

    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ['sqlite-2.sqlite3', 'sqlite-3.sqlite3']
