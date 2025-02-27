import email.utils
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import doit.tools
import jinja2

try:
    import tomllib
except:
    import tomli as tomllib


class C:  # onstants
    NAME = "jupikchr"
    UTF8 = dict(encoding="utf-8")
    PIKCHR_CHECKIN = "d690d1fd06b3d60f"
    PIKCHR_URL = f"https://pikchr.org/home/tarball/{PIKCHR_CHECKIN}/pikchr.tar.gz"
    PIKCHR_PATHS = ["homepage.md", "doc", "tests", "examples", "README.md"]


class P:  # aths
    DODO = Path(__file__)
    ROOT = DODO.parent
    PACKAGE_JSON = ROOT / "package.json"
    PYPROJECT_TOML = ROOT / "pyproject.toml"
    EXAMPLES = ROOT / "examples"
    PACKAGES = ROOT / "packages"
    EXT_PACKAGE = PACKAGES / C.NAME
    ICON = EXT_PACKAGE / "style/img/alpha-p-box.svg"
    DOCS = ROOT / "docs"
    DOCS_STATIC = DOCS / "_static"
    DOCS_ICON = DOCS_STATIC / "icon.svg"


class D:  # ata
    PACKAGE_JSON = json.loads(P.PACKAGE_JSON.read_text(**C.UTF8))
    JS_SCRIPTS = PACKAGE_JSON["scripts"]
    JS_TASKS = PACKAGE_JSON["doit"]["tasks"]
    PYPROJECT_TOML = tomllib.loads(P.PYPROJECT_TOML.read_text(**C.UTF8))
    PY_VERSION = PYPROJECT_TOML["project"]["version"]
    JS_VERSION = PY_VERSION.replace("a", "-alpha").replace("b", "-beta")


class B:  # uild
    BUILD = P.ROOT / "build"
    PIKCHR_TARBALL = BUILD / f"pikchr-{C.PIKCHR_CHECKIN}.tar.gz"
    UPSTREAM_EXAMPLES = P.EXAMPLES / "pikchr"
    PIKCHR_SRC = BUILD / f"pikchr-{C.PIKCHR_CHECKIN}"
    DOCS = BUILD / "docs"
    DIST = P.ROOT / "dist"
    SHA256SUMS = DIST / "SHA256SUMS"


class T:  # template
    D = D.__dict__
    P = P.__dict__


class U:  # tilities
    def expand_paths(paths_or_globs):
        paths = []
        for path in paths_or_globs:
            if isinstance(path, dict):
                if "template" in path:
                    paths += [
                        P.ROOT / jinja2.Template(path["template"]).render(**T.__dict__)
                    ]
                    continue
                elif "ref" in path:
                    current = D.JS_TASKS
                    for bit in path["ref"].split("/"):
                        current = current[bit]
                    paths += U.expand_paths(current)
                else:
                    raise ValueError(f"don't know what to do with {path}")
            elif "*" not in path:
                paths += [P.ROOT / path]
            else:
                paths += [*P.ROOT.glob(path)]
        return sorted(set([p for p in paths if not p.is_dir()]))

    def source_date_epoch():
        return (
            subprocess.check_output(["git", "log", "-1", "--format=%ct"])
            .decode("utf-8")
            .strip()
        )

    def fetch_one(url, dest):
        if dest.exists():
            return

        if not dest.parent.exists():
            dest.parent.mkdir(parents=True)

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            with urllib.request.urlopen(url) as response:
                tmp_dest = tdp / dest.name
                with tmp_dest.open("wb") as fd:
                    shutil.copyfileobj(response, fd)
                last_modified = response.headers.get("Last-Modified")
                if last_modified:
                    epoch_time = time.mktime(email.utils.parsedate(last_modified))
                    os.utime(tmp_dest, (epoch_time, epoch_time))
            shutil.copy2(tmp_dest, dest)

    def extract_one(archive: Path, dest: Path):
        """extract the contents of an archive to a path."""
        if dest.exists():
            shutil.rmtree(dest)

        dest.mkdir(parents=True)

        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(dest)
        elif archive.name.endswith(".tar.gz"):
            mode = "r:bz2" if archive.name.endswith(".bz2") else "r:gz"
            with tarfile.open(archive, mode) as tf:
                U.safe_extract_all(tf, dest)
        else:
            raise ValueError(f"Unrecognized archive format {archive.name}")

    def is_within_directory(directory, target):
        abs_directory = os.path.abspath(directory)
        abs_target = os.path.abspath(target)
        prefix = os.path.commonprefix([abs_directory, abs_target])
        return prefix == abs_directory

    def safe_extract_all(tar, path=".", members=None, *, numeric_owner=False):
        for member in tar.getmembers():
            member_path = os.path.join(path, member.name)
            if not U.is_within_directory(path, member_path):
                raise Exception("Attempted Path Traversal in Tar File")
        tar.extractall(path, members, numeric_owner=numeric_owner)

    def copy_one(src, dest):
        if dest.is_dir():
            shutil.rmtree(dest)
        elif dest.exists():
            dest.unlink()

        if not dest.parent.exists():
            dest.parent.mkdir(parents=True)

        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)

    def hash_files(hashfile, root, hash_deps, quiet=False):
        from hashlib import sha256

        if hashfile.exists():
            hashfile.unlink()

        lines = [
            f"{sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}"
            for p in sorted(hash_deps)
        ]

        output = "\n".join(lines)
        if not quiet:
            print(output)
        hashfile.write_text(output)


class E:  # env
    SOURCE_DATE_EPOCH = U.source_date_epoch()


os.environ.update(SOURCE_DATE_EPOCH=E.SOURCE_DATE_EPOCH)


def task_js():
    for task_name, task in D.JS_TASKS.items():
        full_task = dict(
            name=f"{task_name}",
            actions=[
                (doit.tools.create_folder, [B.DIST]),
                (doit.tools.create_folder, [B.BUILD]),
                ["jlpm", task_name],
            ],
            **task,
        )

        for path_key in ["file_dep", "targets"]:
            full_task[path_key] = U.expand_paths(full_task[path_key])

        yield full_task


def task_examples():
    if not B.PIKCHR_TARBALL.exists():
        yield dict(
            name="fetch",
            actions=[(U.fetch_one, [C.PIKCHR_URL, B.PIKCHR_TARBALL])],
            targets=[B.PIKCHR_TARBALL],
        )
    upstream_hashes = B.UPSTREAM_EXAMPLES / "SHA256SUMS"
    yield dict(
        name="extract",
        file_dep=[B.PIKCHR_TARBALL],
        actions=[
            (U.extract_one, [B.PIKCHR_TARBALL, B.PIKCHR_SRC]),
            *[
                (U.copy_one, [B.PIKCHR_SRC / "pikchr" / p, B.UPSTREAM_EXAMPLES / p])
                for p in C.PIKCHR_PATHS
            ],
            lambda: U.hash_files(
                upstream_hashes,
                B.UPSTREAM_EXAMPLES,
                [
                    p
                    for p in B.UPSTREAM_EXAMPLES.rglob("*")
                    if not p.is_dir() and p != upstream_hashes
                ],
                True,
            ),
        ],
        targets=[upstream_hashes],
    )


def task_docs():
    yield dict(
        name="copy:icon",
        file_dep=[P.ICON],
        targets=[P.DOCS_ICON],
        actions=[(U.copy_one, [P.ICON, P.DOCS_ICON])],
    )


def task_binder():
    """get up to a working local development setup."""
    yield dict(
        name="preflight",
        actions=[
            lambda: print(
                """
        ready to start work with:

            jupyter lab --no-browser --debug

        to rebuild the extension when sources change, run this in another terminal:

            jlpm watch
        """
            )
        ],
        task_dep=["js:py:setup:ext", "examples"],
    )


def task_dist():
    file_dep = U.expand_paths(
        [*D.JS_TASKS["dist:npm"]["targets"], *D.JS_TASKS["dist:py"]["targets"]]
    )

    yield dict(
        name="hash",
        targets=[B.SHA256SUMS],
        file_dep=file_dep,
        actions=[(U.hash_files, [B.SHA256SUMS, B.DIST, file_dep])],
    )
