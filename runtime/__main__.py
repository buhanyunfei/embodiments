#!/usr/bin/env python3
"""python -m embodiments — CLI for managing embodiment packages.

Usage:
    python -m embodiments install <zip>      # extract zip to ~/.embodiments/packages/
    python -m embodiments install <dir>      # symlink dev package into ~/.embodiments/packages/
    python -m embodiments list               # list installed packages
    python -m embodiments remove <id>        # uninstall a package
"""
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path


def _packages_dir() -> Path:
    d = Path.home() / ".embodiments" / "packages"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dist_dir() -> Path:
    d = Path.home() / ".embodiments" / "dist"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pkg_name_from_zip(z: zipfile.ZipFile, zip_path: Path) -> str:
    names = z.namelist()
    roots = {n.split("/")[0] for n in names if "/" in n}
    if len(roots) == 1:
        return roots.pop()
    for n in names:
        if n.endswith("embodiment.yaml"):
            try:
                import yaml
                data = yaml.safe_load(io.TextIOWrapper(z.open(n), encoding="utf-8")) or {}
                return data.get("package_id", zip_path.stem.split("-")[0])
            except Exception:
                pass
    return zip_path.stem.split("-")[0]


def cmd_install(args: list):
    if not args:
        print("usage: install <zip|dir>", file=sys.stderr)
        sys.exit(1)

    src = Path(args[0])
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        sys.exit(1)

    packages_dir = _packages_dir()

    if src.is_dir():
        if not (src / "embodiment.yaml").exists():
            print(f"error: {src} is not an embodiment package (no embodiment.yaml)", file=sys.stderr)
            sys.exit(1)
        dest = packages_dir / src.name
        if dest.exists() or dest.is_symlink():
            print(f"error: {src.name} already installed — run 'remove' first", file=sys.stderr)
            sys.exit(1)
        dest.symlink_to(src.resolve())
        print(f"installed {src.name} → {dest} (symlink, dev mode)")

    elif src.suffix == ".zip" or src.name.endswith(".embodiment.zip"):
        with zipfile.ZipFile(src, "r") as z:
            pkg_name = _pkg_name_from_zip(z, src)
            dest = packages_dir / pkg_name
            if dest.exists():
                print(f"error: {pkg_name} already installed — run 'remove' first", file=sys.stderr)
                sys.exit(1)
            z.extractall(packages_dir)
        dist = _dist_dir() / src.name
        if not dist.exists():
            shutil.copy2(src, dist)
        print(f"installed {pkg_name} → {dest}")

    else:
        print(f"error: unsupported format '{src.suffix}' — expected .zip or directory", file=sys.stderr)
        sys.exit(1)


def cmd_list(args: list):
    packages_dir = _packages_dir()
    pkgs = sorted(
        d for d in packages_dir.iterdir()
        if (d / "embodiment.yaml").exists()
    )
    if not pkgs:
        print("no packages installed  (~/.embodiments/packages/ is empty)")
        return
    print(f"installed packages  ({packages_dir})")
    for pkg_dir in pkgs:
        tag = " [symlink]" if pkg_dir.is_symlink() else ""
        # Try to read version
        try:
            import yaml
            data = yaml.safe_load((pkg_dir / "embodiment.yaml").read_text(encoding="utf-8")) or {}
            version = data.get("version", "?")
            name = data.get("name", pkg_dir.name)
        except Exception:
            version, name = "?", pkg_dir.name
        print(f"  {pkg_dir.name}  v{version}  — {name}{tag}")


def cmd_remove(args: list):
    if not args:
        print("usage: remove <package_id>", file=sys.stderr)
        sys.exit(1)
    packages_dir = _packages_dir()
    dest = packages_dir / args[0]
    if not dest.exists() and not dest.is_symlink():
        print(f"error: '{args[0]}' is not installed", file=sys.stderr)
        sys.exit(1)
    if dest.is_symlink():
        dest.unlink()
    else:
        shutil.rmtree(dest)
    print(f"removed {args[0]}")


COMMANDS = {
    "install": cmd_install,
    "list": cmd_list,
    "remove": cmd_remove,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__.strip())
        sys.exit(0 if len(sys.argv) < 2 else 1)
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
