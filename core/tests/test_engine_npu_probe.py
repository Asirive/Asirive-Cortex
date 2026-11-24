from cortex_core.engine.npu_probe import probe


def tree(tmp_path, fastrpc=True, cdsp_state="running", lib=False):
    dev, rp, lib_dir = tmp_path / "dev", tmp_path / "remoteproc", tmp_path / "opt" / "qcom"
    dev.mkdir()
    if fastrpc:
        (dev / "fastrpc-cdsp").write_text("")
    r = rp / "remoteproc0"
    r.mkdir(parents=True)
    (r / "name").write_text("cdsp\n")
    (r / "state").write_text(cdsp_state + "\n")
    if lib:
        d = lib_dir / "a" / "b"
        d.mkdir(parents=True)
        (d / "libQnnHtp.so").write_text("")
    return dict(dev=dev, remoteproc=rp, lib_dirs=(lib_dir,))


def test_reachable_when_fastrpc_and_cdsp_running(tmp_path):
    r = probe(**tree(tmp_path))
    assert r.reachable is True
    assert r.fastrpc_nodes == ["fastrpc-cdsp"]
    assert r.dsp == [{"name": "cdsp", "state": "running"}]


def test_not_reachable_without_fastrpc(tmp_path):
    r = probe(**tree(tmp_path, fastrpc=False))
    assert r.reachable is False
    assert any("fastrpc" in n for n in r.notes)


def test_cdsp_offline(tmp_path):
    r = probe(**tree(tmp_path, cdsp_state="offline"))
    assert r.reachable is False
    assert any("cdsp" in n for n in r.notes)


def test_finds_qnn_lib(tmp_path):
    r = probe(**tree(tmp_path, lib=True))
    assert len(r.qnn_libs) == 1 and r.qnn_libs[0].endswith("libQnnHtp.so")


def test_missing_dirs_do_not_raise(tmp_path):
    r = probe(dev=tmp_path / "x", remoteproc=tmp_path / "y", lib_dirs=(tmp_path / "z",))
    assert r.reachable is False and r.fastrpc_nodes == [] and r.dsp == [] and r.qnn_libs == []
