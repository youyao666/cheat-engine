"""Setup for the Cheat Engine CLI-Anything harness."""

from pathlib import Path

from setuptools import find_namespace_packages, setup


README = Path(__file__).parent / "cli_anything" / "cheat_engine" / "README.md"

setup(
    name="cli-anything-cheat-engine",
    version="0.4.0",
    description="AI-oriented CLI harness for Cheat Engine",
    long_description=README.read_text(encoding="utf-8") if README.exists() else "",
    long_description_content_type="text/markdown",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    python_requires=">=3.10",
    install_requires=["click>=8.0", "prompt-toolkit>=3.0"],
    extras_require={"test": ["pytest>=7.0"]},
    entry_points={
        "console_scripts": [
            "cli-anything-cheat-engine=cli_anything.cheat_engine.cheat_engine_cli:main",
            "ce-ai=cli_anything.cheat_engine.cheat_engine_cli:main",
        ]
    },
    package_data={
        "cli_anything.cheat_engine": ["README.md", "skills/*.md"],
    },
    include_package_data=True,
    zip_safe=False,
)
