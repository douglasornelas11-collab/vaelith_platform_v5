from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi import FastAPI


_LEGACY_MODULE_NAME = "_vaelith_static_runtime_legacy"


def _legacy_module():
    existing = sys.modules.get(_LEGACY_MODULE_NAME)
    if existing is not None:
        return existing

    legacy_path = Path(__file__).resolve().parent.parent / "static_runtime.py"
    spec = importlib.util.spec_from_file_location(_LEGACY_MODULE_NAME, legacy_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Não foi possível carregar o runtime visual consolidado.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[_LEGACY_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def install(app: FastAPI) -> None:
    if getattr(app.state, "_vaelith_static_legacy_installed", False):
        return
    app.state._vaelith_static_legacy_installed = True
    _legacy_module().install(app)
