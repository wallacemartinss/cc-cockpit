# Packaging

| File | What it produces |
|---|---|
| `build-deb.sh` | `dist/cc-cockpit_<version>_all.deb` for Debian/Ubuntu |
| `PKGBUILD` + `.SRCINFO` | the AUR package for Arch |

Both are architecture-independent: the project is pure Python, and the GTK
bindings come from the distribution.

## Releasing

Bump `__version__` in `cockpit/__init__.py`, mirror it in `PKGBUILD`/`.SRCINFO`
(`pkgver`), then tag:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

The `release` workflow builds the wheel, the sdist and the `.deb`, publishes to
PyPI via trusted publishing and attaches everything to the GitHub release.

## AUR

The AUR repository is separate from this one:

```bash
git clone ssh://aur@aur.archlinux.org/cc-cockpit.git aur
cp packaging/PKGBUILD packaging/.SRCINFO aur/
cd aur && git commit -am "cc-cockpit 0.2.0" && git push
```

Regenerate `.SRCINFO` with `makepkg --printsrcinfo > .SRCINFO` whenever the
`PKGBUILD` changes; the copy here is kept in sync by hand so the AUR upload is
a copy, not a rewrite.

Check the build before pushing: `makepkg -si` in a clean directory.
