#  Copyright (c) 2025, Exactpro Systems LLC
#  www.exactpro.com
#  Build Software to Test Software
#
#  All rights reserved.
#  This is unpublished, licensed software, confidential and proprietary
#  information which is the property of Exactpro Systems LLC or its licensors.
import logging
import subprocess
import venv
from pathlib import Path

logger: logging.Logger = logging.getLogger('j-sp')

def register_kernel(venv_dir: Path, kernel_name: str, kernel_display_name: str):
    _create_venv_if_needed(venv_dir)
    result = subprocess.run(
        [
            str(venv_dir / "bin" / "python"),
            "-m",
            "ipykernel",
            "install",
            "--user",
            "--name",
            kernel_name,
            "--display-name",
            kernel_display_name,
        ],
        check=True,
    )
    if result.returncode == 0:
        logger.info(
            "created '%s' kernel using '%s' virtual environment",kernel_name, venv_dir)
    else:
        raise RuntimeError(
            f"creation '{kernel_name}' kernel using '{venv_dir}' virtual environment failure: {result.stdout.strip()}")

def _create_venv_if_needed(venv_dir: Path):
    if venv_dir.exists():
        logger.info('reuse %s virtual env', venv_dir)
        return
    venv.create(venv_dir, with_pip=True, system_site_packages=True)
    logger.info('created %s virtual env', venv_dir)