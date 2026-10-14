"""Package a locally built official OFIQ runtime with hashes, ABI and notices."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ofiq import COMMIT, VERSION, MODEL_BUNDLE_SHA, CONFIG_SHA, digest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'libraries', 'model-bundle', 'abi', 'destination'):
        p.add_argument('--' + key, required=True, type=Path)
    args = p.parse_args(); source = args.source.resolve(); target = args.destination.resolve()
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != COMMIT: raise ValueError('Build must use the pinned official source')
    changed = subprocess.check_output(['git', '-C', str(source), 'diff', '--name-only'], text=True).splitlines()
    if set(changed) - {'OFIQlib/CMakeLists.macos.cmake', 'data/models/README.md'}:
        raise ValueError('Official quality source has been modified')
    if digest(args.model_bundle) != MODEL_BUNDLE_SHA: raise ValueError('Model bundle does not match the validated official archive')
    if digest(source / 'data/ofiq_config.jaxn') != CONFIG_SHA: raise ValueError('Canonical OFIQ mappings changed')
    # Upstream extraction replaces its tracked model README as well as weights.
    # Verify the actual installed files against the pinned archive before packing.
    with zipfile.ZipFile(args.model_bundle) as archive:
        for entry in archive.infolist():
            if entry.is_dir(): continue
            name = Path(entry.filename)
            if name.is_absolute() or '..' in name.parts: raise ValueError('Unsafe model archive path')
            expected = hashlib.sha256(archive.read(entry)).hexdigest()
            if digest(source / 'data' / name) != expected: raise ValueError('Installed model differs from official bundle')
    if (target / 'manifest.json').exists(): raise ValueError('Use a fresh runtime destination')
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source / 'data/models', target / 'data/models')
    shutil.copy(source / 'data/ofiq_config.jaxn', target / 'data/ofiq_config.jaxn')
    (target / 'lib').mkdir(exist_ok=True)
    for f in args.libraries.iterdir():
        if f.is_file() and ('.so' in f.name or f.suffix in ('.dylib', '.dll')):
            shutil.copy(f, target / 'lib' / f.name)
    candidates = list((target / 'lib').glob('*ofiq_c.*'))
    if len(candidates) != 1: raise ValueError('One native C API library is required')
    (target / 'notices').mkdir(exist_ok=True)
    shutil.copy(source / 'LICENSE.md', target / 'notices/OFIQ-LICENSE.md')
    source_diff = subprocess.check_output(['git', '-C', str(source), 'diff'], text=True)
    (target / 'notices/build-diff.patch').write_text(source_diff)
    files = {f.relative_to(target).as_posix(): digest(f) for f in sorted(target.rglob('*')) if f.is_file()}
    record = dict(version=VERSION, source_commit=COMMIT, model_bundle_sha256=MODEL_BUNDLE_SHA,
        library=candidates[0].relative_to(target).as_posix(), config='data/ofiq_config.jaxn',
        abi_sizes=json.loads(args.abi.read_text()), files=files,
        build_note='Official quality code; Mac C API target added without changing its implementation.')
    (target / 'manifest.json').write_text(json.dumps(record, indent=2))
    print('Packaged OFIQ', VERSION, 'with', len(files), 'verified assets')


if __name__ == '__main__': main()
