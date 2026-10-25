from pipeline.cli import main


def test_custom_data_root_cannot_publish_default_repository(tmp_path, monkeypatch, capsys):
    import pipeline.publish as publication

    def forbidden(*args, **kwargs):
        raise AssertionError("A custom data root must never mutate the default GitHub repository")

    monkeypatch.setattr(publication, "publish", forbidden)
    assert main(["--root", str(tmp_path), "publish"]) == 1
    assert "thư mục dự án mặc định" in capsys.readouterr().out
