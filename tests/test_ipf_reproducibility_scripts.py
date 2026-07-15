from pathlib import Path

import pytest

from scripts import generate_ipf_pseudobulk_s7 as pseudobulk
from scripts import recreate_ipf_lrdata_b1 as lrdata


def test_pseudobulk_requires_explicit_input(tmp_path: Path) -> None:
    missing = tmp_path / "n_ipf.h5ad"

    with pytest.raises(SystemExit, match=f"Input AnnData file is unavailable: {missing}"):
        pseudobulk.main(["--input", str(missing)])


def test_lrdata_derives_input_from_requested_sp_enrich_root(tmp_path: Path) -> None:
    expected = tmp_path / "data" / "n_ipf.h5ad"

    with pytest.raises(SystemExit, match=f"Input not found: {expected}"):
        lrdata.main(["--sp-enrich-root", str(tmp_path)])
