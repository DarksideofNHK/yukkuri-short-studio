#!/usr/bin/env python3
"""素材一式を最後まで作る：build_premiere.py → build_anim.py → build_premiere.py（動く図を入れる）→ check_package.py

usage:
  python3 build_all.py --spec path/to/spec.json [--out 出力フォルダ] [--no-measure]
音声を作り直したときも、これ1つで並べ直し・動きの作り直し・XML まで全部そろう。
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(script, *args):
    r = subprocess.run([sys.executable, str(HERE / script), *args])
    if r.returncode != 0:
        raise SystemExit(f'{script} が失敗した（終了コード {r.returncode}）')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spec', required=True)
    ap.add_argument('--out')
    ap.add_argument('--no-measure', action='store_true')
    a = ap.parse_args()
    common = ['--spec', a.spec] + (['--out', a.out] if a.out else [])
    run('build_premiere.py', *common, *(['--no-measure'] if a.no_measure else []))
    run('build_anim.py', *common)
    run('build_premiere.py', *common, *(['--no-measure'] if a.no_measure else []))
    run('check_package.py', *common)


if __name__ == '__main__':
    main()
