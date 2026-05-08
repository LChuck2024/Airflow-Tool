import subprocess
import sys


def _run(cmd: list[str]) -> None:
    print(f"[pipeline] run: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main() -> None:
    try:
        _run([sys.executable, "collector.py"])
        _run([sys.executable, "transform.py"])
        print("[pipeline] ETL done")
    except subprocess.CalledProcessError as exc:
        print(f"[pipeline] failed: {exc}")
        raise


if __name__ == "__main__":
    main()
