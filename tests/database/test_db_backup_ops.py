import gzip
import hashlib
from pathlib import Path

import duckdb
import pytest

from scripts.db_backup_ops import compress_cloud_backups, compress_local_backups, restore_backup
from scripts import db_diff_report
from src.storage import gcs
from src.storage.backup_history import compress_backup, sha256_file


class Blob:
    def __init__(self, bucket, name, data=b''):
        self.bucket, self.name, self.data = bucket, name, data
        self.generation = 7

    def download_to_filename(self, path, *, if_generation_match):
        assert if_generation_match == self.generation
        Path(path).write_bytes(self.data)

    def upload_from_filename(self, path, *, if_generation_match):
        assert if_generation_match == 0
        self.data = Path(path).read_bytes()
        self.bucket.uploads.append(self.name)

    def delete(self, *, if_generation_match):
        assert if_generation_match == self.generation
        del self.bucket.blobs[self.name]


class Bucket:
    def __init__(self):
        self.blobs, self.uploads = {}, []

    def blob(self, name):
        if name not in self.blobs:
            self.blobs[name] = Blob(self, name)
        return self.blobs[name]

    def get_blob(self, name):
        return self.blobs.get(name)

    def list_blobs(self, prefix):
        return [b for b in self.blobs.values() if b.name.startswith(prefix)]


def tiny_db(path, value=2000000, extra=False):
    with duckdb.connect(str(path)) as db:
        db.execute('''CREATE TABLE holdings (
            asset_id VARCHAR, snapshot_date DATE, is_shadow BOOLEAN, market_value DOUBLE,
            quantity DOUBLE, cost_price_unit DOUBLE, market_price_unit DOUBLE,
            source_system VARCHAR, currency VARCHAR)''')
        db.execute("INSERT INTO holdings VALUES ('A', '2026-01-01', false, ?, 1, 1, 1, 'PIS', 'CNY')", [value])
        db.execute("INSERT INTO holdings VALUES ('B', '2025-12-01', false, 100, 1, 1, 1, 'PIS', 'CNY')")
        db.execute("INSERT INTO holdings VALUES ('B', '2025-11-01', false, 999, 1, 1, 1, 'PIS', 'CNY')")
        db.execute("INSERT INTO holdings VALUES ('C', '2026-02-01', true, 99999, 1, 1, 1, 'PIS', 'CNY')")
        if extra:
            db.execute('CREATE TABLE extra (id INTEGER)')
            db.execute('INSERT INTO extra VALUES (1)')


def test_local_conversion_dry_run_verified_and_delete(tmp_path, capsys):
    original = tmp_path / 'backup.duckdb'
    original.write_bytes(b'abc' * 10000)
    digest = sha256_file(original)
    dest = compress_backup(original)
    assert not dest.exists() and original.exists()
    compress_backup(original, execute=True)
    assert original.exists()
    assert sha256_file(dest, compressed=True) == digest
    with pytest.raises(FileExistsError):
        compress_backup(original, execute=True, delete_originals=True)
    assert original.exists()
    other = tmp_path / 'other.duckdb'
    other.write_bytes(b'delete only after verify')
    compress_local_backups(tmp_path, execute=True, delete_originals=True)
    assert not other.exists() and original.exists()
    assert 'bytes; SHA-256 verified' in capsys.readouterr().out


def test_local_hash_mismatch_preserves_original(tmp_path, monkeypatch):
    from src.storage import backup_history
    source = tmp_path / 'backup.duckdb'
    source.write_bytes(b'x')
    monkeypatch.setattr(backup_history, 'gzip_copy', lambda src, dst: dst.write_bytes(gzip.compress(b'wrong')))
    with pytest.raises(ValueError, match='mismatch'):
        compress_backup(source, execute=True, delete_originals=True)
    assert source.exists() and not Path(str(source) + '.gz').exists()


def test_cloud_conversion_and_skip_siblings():
    bucket = Bucket()
    bucket.blob('backups/old.duckdb').data = b'abc' * 10000
    compress_cloud_backups(bucket)
    assert bucket.uploads == []
    compress_cloud_backups(bucket, execute=True)
    assert bucket.uploads == ['backups/old.duckdb.gz']
    assert gzip.decompress(bucket.blobs[bucket.uploads[0]].data) == b'abc' * 10000
    compress_cloud_backups(bucket, execute=True, delete_originals=True)
    assert 'backups/old.duckdb' in bucket.blobs  # existing sibling is never grounds to delete
    bucket.blob('backups/remove.duckdb').data = b'remove'
    compress_cloud_backups(bucket, execute=True, delete_originals=True)
    assert 'backups/remove.duckdb' not in bucket.blobs


def test_cloud_corruption_prevents_delete(monkeypatch):
    bucket = Bucket()
    bucket.blob('backups/old.duckdb').data = b'original'
    original_upload = Blob.upload_from_filename
    def corrupt(self, path, **kwargs):
        original_upload(self, path, **kwargs)
        self.data = gzip.compress(b'wrong')
    monkeypatch.setattr(Blob, 'upload_from_filename', corrupt)
    with pytest.raises(ValueError, match='after upload'):
        compress_cloud_backups(bucket, execute=True, delete_originals=True)
    assert 'backups/old.duckdb' in bucket.blobs


@pytest.mark.parametrize('reason', ['ab', 'UPPER', '../bad', 'x' * 41, 'has_space'])
def test_snapshot_invalid_reason(reason):
    with pytest.raises(ValueError):
        gcs.create_named_snapshot(Bucket(), reason)


def test_snapshot_preserves_canonical():
    bucket = Bucket()
    canonical = bucket.blob('db/unified.duckdb')
    canonical.data = b'canonical'
    name = gcs.create_named_snapshot(bucket, 'pre-migration')
    assert name.startswith('backups/named/') and name.endswith('_pre-migration_unified.duckdb.gz')
    assert gzip.decompress(bucket.blobs[name].data) == canonical.data
    assert bucket.uploads == [name]
    with pytest.raises(FileNotFoundError):
        gcs.create_named_snapshot(Bucket(), 'pre-change')


@pytest.mark.parametrize('compressed', [False, True])
def test_restore_and_readonly_report(tmp_path, capsys, compressed):
    source = tmp_path / 'source.duckdb'
    tiny_db(source)
    contents = source.read_bytes()
    bucket = Bucket()
    name = 'backups/original.duckdb' + ('.gz' if compressed else '')
    bucket.blob(name).data = gzip.compress(contents) if compressed else contents
    target = tmp_path / 'restored.duckdb'
    canonical = tmp_path / 'data' / 'unified.duckdb'
    restore_backup(bucket, name, target, canonical=canonical)
    assert target.read_bytes() == contents
    out = capsys.readouterr().out
    assert hashlib.sha256(contents).hexdigest() in out and 'Integrity:' in out
    assert bucket.uploads == []
    with pytest.raises(FileExistsError):
        restore_backup(bucket, name, target, canonical=canonical)
    with pytest.raises(ValueError):
        restore_backup(bucket, name, canonical, canonical=canonical, overwrite=True)
    restore_backup(bucket, name, target, canonical=canonical, overwrite=True)
    assert target.read_bytes() == contents


def test_restore_corrupt_gzip_leaves_existing_untouched(tmp_path):
    bucket = Bucket()
    bucket.blob('backups/broken.duckdb.gz').data = b'not gzip'
    target = tmp_path / 'existing'
    target.write_bytes(b'original')
    with pytest.raises(gzip.BadGzipFile):
        restore_backup(bucket, 'broken.duckdb.gz', target, canonical=tmp_path / 'canonical', overwrite=True)
    assert target.read_bytes() == b'original'


def test_diff_report_counts_nw_and_readonly(tmp_path, capsys, monkeypatch):
    from src.validation import data_integrity_gate as gate
    monkeypatch.setattr(gate, '_log_report', lambda *args: pytest.fail('audit writes forbidden'))
    old, new = tmp_path / 'old.duckdb', tmp_path / 'new.duckdb'
    tiny_db(old)
    tiny_db(new, 2100000, extra=True)
    hashes = [sha256_file(p) for p in (old, new)]
    assert db_diff_report.inspect_database(old)['net_worth'] == 2000100
    assert db_diff_report.diff_report(old, new) == 0
    out = capsys.readouterr().out
    assert '| main.extra | 0 | 1 | +1 |' in out
    assert '| main.holdings |' not in out  # unchanged counts omitted
    assert '2,000,100.00 → 2,100,100.00' in out
    assert hashes == [sha256_file(p) for p in (old, new)]
    with duckdb.connect(str(new)) as db:
        db.execute("UPDATE holdings SET market_value = -1 WHERE asset_id = 'A'")
    assert db_diff_report.diff_report(old, new) == 1


def test_mutating_commands_default_to_dry_run(monkeypatch, tmp_path):
    from scripts import maint_db
    monkeypatch.setattr(maint_db, '_require_bucket', lambda: pytest.fail('no cloud discovery on dry-run'))
    monkeypatch.setattr(maint_db, 'LOCAL_DB', tmp_path / 'not-opened.duckdb')
    maint_db.compact_local()
    maint_db.compact_cloud()
    maint_db.pull_cloud(yes=True, force=True)
    source = tmp_path / 'cloud-mirror-old.duckdb'
    source.write_bytes(b'x')
    maint_db._rotate_backups(tmp_path, 'cloud-mirror-*.duckdb', 0)
    assert source.exists() and not Path(str(source) + '.gz').exists()


def test_cli_all_cannot_imply_execute(monkeypatch):
    import sys
    from scripts import maint_db
    seen = []
    monkeypatch.setattr(sys, 'argv', ['maint_db.py', '--all'])
    for name in ('prune_backups', 'compact_local', 'compact_cloud'):
        monkeypatch.setattr(maint_db, name, lambda *, execute: seen.append(execute))
    maint_db.main()
    assert seen == [False, False, False]


def test_cli_delete_originals_requires_both_flags(monkeypatch):
    import sys
    from scripts import maint_db
    monkeypatch.setattr(sys, 'argv', ['maint_db.py', '--compress-existing', '--delete-originals'])
    with pytest.raises(SystemExit) as error:
        maint_db.main()
    assert error.value.code == 2


def test_gsutil_transport_is_generation_pinned(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from scripts import gcs_backup_cli
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='    Generation: 42\n', stderr='')
    monkeypatch.setattr(gcs_backup_cli.subprocess, 'run', run)
    bucket = gcs_backup_cli.BackupBucket('fake')
    blob = bucket.get_blob('backups/copy.duckdb')
    blob.download_to_filename(str(tmp_path / 'copy'), if_generation_match=blob.generation)
    blob.upload_from_filename(str(tmp_path / 'copy'), if_generation_match=0)
    blob.delete(if_generation_match=42)
    assert calls[1][2] == 'gs://fake/backups/copy.duckdb#42'
    assert calls[2][1:4] == ['-h', 'x-goog-if-generation-match:0', 'cp']
    assert calls[4][1:4] == ['-h', 'x-goog-if-generation-match:42', 'rm']


def test_gsutil_transport_distinguishes_missing_from_error(monkeypatch):
    from types import SimpleNamespace
    from scripts import gcs_backup_cli
    monkeypatch.setattr(gcs_backup_cli.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=1, stdout='', stderr='No URLs matched'))
    assert gcs_backup_cli.BackupBucket('fake').get_blob('missing') is None
    monkeypatch.setattr(gcs_backup_cli.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=1, stdout='', stderr='AccessDenied'))
    with pytest.raises(RuntimeError, match='AccessDenied'):
        gcs_backup_cli.BackupBucket('fake').get_blob('denied')
