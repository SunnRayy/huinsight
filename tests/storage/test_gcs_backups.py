from pathlib import Path

import pytest

from src.storage import gcs


class FakeBlob:
    def __init__(self, name):
        self.name, self.generation = name, 7

    def upload_from_filename(self, path, if_generation_match=None):
        raise AssertionError("test must override upload")


class FakeBucket:
    def __init__(self):
        self.blobs = {}

    def blob(self, name):
        if name not in self.blobs:
            self.blobs[name] = FakeBlob(name)
        return self.blobs[name]

    def get_blob(self, name):
        return self.blobs.get(name)


class FakeClient:
    def __init__(self, bucket):
        self._bucket = bucket

    def bucket(self, name):
        return self._bucket


@pytest.mark.parametrize("failure", ["gzip", "tempdir"])
def test_backup_bytes_order_and_compression_fallback(tmp_path, monkeypatch, caplog, failure):
    import gzip
    source = tmp_path / 'source.duckdb'
    source.write_bytes(b'backup content' * 1000)
    calls = []
    bucket = FakeBucket()

    def upload(blob, path, if_generation_match=None):
        calls.append((blob.name, Path(path).read_bytes(), if_generation_match))

    monkeypatch.setattr(FakeBlob, 'upload_from_filename', upload)
    monkeypatch.setattr(gcs, '_get_client', lambda: FakeClient(bucket))
    gcs.upload_db_to_gcs('fake', str(source))
    assert calls[0][0].endswith('.gz')
    assert gzip.decompress(calls[0][1]) == source.read_bytes()
    assert calls[1][0] == 'db/unified.duckdb'
    assert calls[1][2] == 0
    calls.clear()
    if failure == 'gzip':
        monkeypatch.setattr(gcs, 'gzip_copy', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    else:
        monkeypatch.setattr(gcs.tempfile, 'TemporaryDirectory', lambda **kwargs: (_ for _ in ()).throw(OSError('disk full')))
    gcs.upload_db_to_gcs('fake', str(source))
    assert calls[0][0].endswith('.duckdb')
    assert calls[0][1] == source.read_bytes()
    assert calls[1][0] == 'db/unified.duckdb'
    assert 'compression failed' in caplog.text


def test_failed_backup_blocks_canonical_upload(tmp_path, monkeypatch):
    source = tmp_path / 'source.duckdb'
    source.write_bytes(b'x')
    bucket = FakeBucket()
    def upload(blob, path, **kwargs):
        assert blob.name.startswith('backups/')
        raise OSError('upload failed')
    monkeypatch.setattr(FakeBlob, 'upload_from_filename', upload)
    monkeypatch.setattr(gcs, '_get_client', lambda: FakeClient(bucket))
    with pytest.raises(OSError):
        gcs.upload_db_to_gcs('fake', str(source))
    assert 'db/unified.duckdb' not in bucket.blobs
