"""Package only the standalone app, moving workflow templates into place."""

import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def package(output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        workflow_directory = "workflows" if (ROOT / "workflows").exists() else ".github/workflows"
        for directory in ("scripts", "web", "tests", "config", "data", workflow_directory):
            for path in sorted((ROOT / directory).rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                relative = path.relative_to(ROOT)
                name = str(relative).replace("workflows/", ".github/workflows/", 1) if directory == "workflows" else str(relative)
                archive.write(path, name)
        for name in (".gitignore", "README.md", "RESEARCH.md", "package.json"):
            archive.write(ROOT / name, name)
    print(f"Standalone app packaged: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    package(parser.parse_args().output)
