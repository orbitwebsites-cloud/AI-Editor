from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def test_default_render_blueprint_is_free_and_ephemeral():
    blueprint = (REPO / "render.yaml").read_text(encoding="utf-8")
    assert "plan: free" in blueprint
    assert "healthCheckPath: /api/health" in blueprint
    assert "dockerContext: ." in blueprint
    assert "\n    disk:" not in blueprint
    assert "APP_ACCESS_TOKEN" not in blueprint


def test_paid_persistence_is_separate_and_explicit():
    example = (REPO / "render.persistent.example.yaml").read_text(encoding="utf-8")
    assert "Optional paid deployment example" in example
    assert "plan: starter" in example
    assert "mountPath: /app/data" in example


def test_docker_healthcheck_reads_runtime_port():
    dockerfile = (REPO / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "HEALTHCHECK" in dockerfile
    assert "os.environ.get('PORT', '8000')" in dockerfile
    assert "/api/health" in dockerfile
