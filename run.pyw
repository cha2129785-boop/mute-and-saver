# -*- coding: utf-8 -*-
"""
run.pyw — 배포/실행 진입점.
mute_and_saver 패키지는 상대 임포트 구조이므로, 패키지 밖에서 임포트해 실행한다.
pythonw(run.pyw) 또는 PyInstaller 빌드의 진입 스크립트로 사용.
"""
import sys

def _run():
    from mute_and_saver.main import main
    main()

if __name__ == "__main__":
    _run()
