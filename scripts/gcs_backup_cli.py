"""Minimal generation-pinned GCS backup transport for gsutil-only local installs."""
from __future__ import annotations

import subprocess

# Objects over 150 MB make gsutil fork worker processes for a sliced download, and
# on macOS a forked worker segfaults in getaddrinfo (Network.framework). The parent
# then waits forever (seen 2026-11-08 once the DB reached 155 MB). One process
# keeps the transfer threaded without forking.
GSUTIL_NO_FORK = ['-o', 'GSUtil:parallel_process_count=1']


class BackupBucket:
    def __init__(self, name: str):
        self.name = name

    def _run(self, args: list[str], *, missing_ok: bool = False) -> str | None:
        result = subprocess.run(['gsutil', *GSUTIL_NO_FORK, *args], capture_output=True, text=True)
        if result.returncode:
            if missing_ok and ('No URLs matched' in result.stderr or 'matched no objects' in result.stderr):
                return None
            raise RuntimeError(f'gsutil backup operation failed: {result.stderr.strip()}')
        return result.stdout

    def blob(self, name: str):
        return BackupBlob(self, name)

    def get_blob(self, name: str):
        blob = self.blob(name)
        return blob if blob.load(missing_ok=True) else None

    def list_blobs(self, prefix: str):
        output = self._run(['ls', '-r', f'gs://{self.name}/{prefix}**'], missing_ok=True)
        for uri in (output or '').splitlines():
            base = f'gs://{self.name}/'
            if uri.startswith(base) and uri.endswith(('.duckdb', '.duckdb.gz')):
                blob = self.blob(uri[len(base):])
                blob.load()
                yield blob


class BackupBlob:
    def __init__(self, bucket: BackupBucket, name: str):
        self.bucket, self.name = bucket, name
        self.generation = None

    @property
    def uri(self) -> str:
        return f'gs://{self.bucket.name}/{self.name}'

    def load(self, *, missing_ok: bool = False) -> bool:
        output = self.bucket._run(['stat', self.uri], missing_ok=missing_ok)
        if output is None:
            return False
        for line in output.splitlines():
            key, separator, value = line.strip().partition(':')
            if separator and key == 'Generation':
                self.generation = int(value.strip())
                return True
        raise ValueError('GCS metadata missing generation')

    def download_to_filename(self, path: str, *, if_generation_match: int) -> None:
        if if_generation_match is None:
            raise ValueError('A source generation is required')
        self.bucket._run(['cp', f'{self.uri}#{if_generation_match}', path])

    def upload_from_filename(self, path: str, *, if_generation_match: int) -> None:
        self.bucket._run(['-h', f'x-goog-if-generation-match:{if_generation_match}', 'cp', path, self.uri])
        self.load()

    def delete(self, *, if_generation_match: int) -> None:
        self.bucket._run(['-h', f'x-goog-if-generation-match:{if_generation_match}', 'rm', self.uri])
