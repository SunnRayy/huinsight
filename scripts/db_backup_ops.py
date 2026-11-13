"""Explicit backup conversion and restore operations (mockable GCS SDK boundary)."""
from __future__ import annotations

import gzip
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from src.storage.backup_history import compress_backup, gzip_copy, sha256_file


def compress_cloud_backups(bucket, *, execute: bool = False, delete_originals: bool = False) -> None:
    blobs = list(bucket.list_blobs(prefix='backups/'))
    names = {b.name for b in blobs}
    for blob in blobs:
        if not blob.name.endswith('.duckdb') or blob.name + '.gz' in names:
            continue
        if not execute:
            print(f'[DRY-RUN] compress {blob.name}; delete original={delete_originals}')
            continue
        with tempfile.TemporaryDirectory(prefix='uis-cloud-gzip-') as work:
            source = Path(work) / 'original.duckdb'
            compressed = Path(work) / 'backup.gz'
            downloaded = Path(work) / 'verified.gz'
            blob.download_to_filename(str(source), if_generation_match=blob.generation)
            gzip_copy(source, compressed)
            expected = sha256_file(source)
            if sha256_file(compressed, compressed=True) != expected:
                raise ValueError(f'SHA-256 mismatch before upload: {blob.name}')
            target = bucket.blob(blob.name + '.gz')
            target.upload_from_filename(str(compressed), if_generation_match=0)
            # Verify the persisted object, pinned to the generation we just uploaded.
            target.download_to_filename(str(downloaded), if_generation_match=target.generation)
            if sha256_file(downloaded, compressed=True) != expected:
                raise ValueError(f'SHA-256 mismatch after upload: {target.name}')
            print(f'{blob.name}: {source.stat().st_size} -> {downloaded.stat().st_size} bytes; SHA-256 verified')
            if delete_originals and "_KEEP" not in blob.name:
                blob.delete(if_generation_match=blob.generation)


def restore_backup(bucket, name: str, destination: Path, *, canonical: Path, overwrite: bool = False) -> None:
    if name.startswith('backups/'):
        key = name
    else:
        key = 'backups/' + name
    if '..' in PurePosixPath(key).parts or not key.endswith(('.duckdb', '.duckdb.gz')):
        raise ValueError('Expected a backup name under backups/')
    destination = destination.expanduser().absolute()
    resolved = destination.resolve()
    if destination.resolve() == canonical.resolve() or (
        resolved.name == 'unified.duckdb' and resolved.parent.name == 'data'
    ):
        raise ValueError('Refusing canonical local database destination')
    if (destination.exists() or destination.is_symlink()) and not overwrite:
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='uis-restore-', dir=destination.parent) as work:
        download = Path(work) / 'download'
        restored = Path(work) / 'restored.duckdb'
        blob = bucket.get_blob(key)
        if blob is None:
            raise FileNotFoundError(key)
        blob.download_to_filename(str(download), if_generation_match=blob.generation)
        if key.endswith('.gz'):
            with gzip.open(download, 'rb') as source, restored.open('wb') as target:
                shutil.copyfileobj(source, target)
        else:
            shutil.copyfile(download, restored)
        from scripts.db_diff_report import inspect_database, integrity_summary

        result = inspect_database(restored)
        print(f'SHA-256: {sha256_file(restored)}')
        print(f'Integrity: {integrity_summary(result["integrity"])}')
        # Publish only a complete readable copy; failed checks are reported, not hidden.
        if overwrite:
            os.replace(restored, destination)
        else:
            os.link(restored, destination)
    print(f'Restored {key} -> {destination}')


def compress_local_backups(directory: Path, *, execute: bool = False, delete_originals: bool = False) -> None:
    for source in sorted(directory.glob('*.duckdb')):
        if not source.name.startswith('.') and not Path(str(source) + '.gz').exists():
            compress_backup(source, execute=execute, delete_originals=delete_originals)
