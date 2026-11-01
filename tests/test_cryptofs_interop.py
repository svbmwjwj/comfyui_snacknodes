"""Cross-check against Cryptomator's own Java library (cryptofs).

Skipped unless java + mvn are available (CI installs them). Verifies both:
  A) vaults written by this package open in cryptofs with byte-identical files;
  B) vaults created by cryptofs can be unlocked and extended by this package.
"""

import hashlib
import os
import shutil
import subprocess

import pytest

from cloud_drive.vault import CryptomatorVault
from local_provider import LocalProvider

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.join(HERE, "interop")
PASSWORD = "pw-测试-ü"
pytestmark = pytest.mark.skipif(not (shutil.which("java") and shutil.which("mvn")), reason="needs java + mvn")

FILES = {
    "small.png": os.urandom(1000),
    "multi_chunk.png": os.urandom(32 * 1024 * 3 + 5),
    "exact_chunk.bin": os.urandom(32 * 1024),
    "empty.txt": b"",
    "中文 图片 ü.png": os.urandom(77),
    "L" * 200 + ".png": os.urandom(10),  # long name -> .c9s shortening
}


@pytest.fixture(scope="module")
def classpath():
    subprocess.run(["mvn", "-q", "-B", "compile", "dependency:build-classpath", "-Dmdep.outputFile=cp.txt"],
                   cwd=PROJECT, check=True)
    with open(os.path.join(PROJECT, "cp.txt")) as f:
        return os.path.join(PROJECT, "target", "classes") + os.pathsep + f.read().strip()


def _java(classpath, mode, vault):
    env = {**os.environ, "PW": PASSWORD, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    out = subprocess.run(["java", "-Dstdout.encoding=UTF-8", "-Dsun.jnu.encoding=UTF-8", "-cp", classpath,
                          "Check", mode, str(vault), "x"], env=env, check=True, capture_output=True, text=True)
    files = {}
    for line in out.stdout.splitlines():
        if line.startswith("F\t"):
            _, path, size, digest = line.split("\t")
            files[path] = (int(size), digest)
    return files


def _upload_all(vault, folders, tmp_path):
    expected = {}
    for i, (name, data) in enumerate(FILES.items()):
        src = tmp_path / f"src{i}"
        src.write_bytes(data)
        folder = folders[i % len(folders)]
        r = vault.upload(str(src), folder, name)
        clear = r.remote_path.split("/", 1)[1] if vault.vault_path else r.remote_path
        expected["/" + clear] = (len(data), hashlib.sha256(data).hexdigest())
    return expected


def test_cryptofs_reads_our_vault(classpath, tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    vault = CryptomatorVault.create(LocalProvider(drive), "Vault", PASSWORD)
    expected = _upload_all(vault, ["ComfyUI", "ComfyUI/2026-11-01", "ComfyUI/深层/x", "F" * 230], tmp_path)
    assert _java(classpath, "read", drive / "Vault") == expected


def test_we_extend_a_cryptofs_vault(classpath, tmp_path):
    drive = tmp_path / "drive"
    _java(classpath, "create", drive)  # makes /ComfyUI/existing/hello.txt
    vault = CryptomatorVault.unlock(LocalProvider(drive), "", PASSWORD)
    expected = _upload_all(vault, ["ComfyUI/existing", "New"], tmp_path)
    found = _java(classpath, "read", drive)
    assert found.pop("/ComfyUI/existing/hello.txt")[0] == len("made by cryptofs")
    assert found == expected
