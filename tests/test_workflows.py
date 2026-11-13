"""The workflows' checkouts keep no credentials (polyglotic-hq project 032, D5 item 4; project 066, Low 4).

By default `actions/checkout` writes the job's token into the checkout's
git config, where every later step can read it - and so can anything a
dependency runs during `uv sync`, the tests or the build. No job here
fetches or pushes after its checkout (the secret scan lists a pull
request's commits through the API with its own `GITHUB_TOKEN`; the
release's publish job uses `GH_TOKEN` for `gh release create`), so every
checkout says `persist-credentials: false`. Read as the YAML GitHub reads.
"""

from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def checkouts() -> list[tuple[str, dict[str, Any]]]:
    """Every `actions/checkout` step, as (workflow / job, step)."""
    found = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in workflow["jobs"].items():
            for step in job.get("steps") or []:
                if str(step.get("uses", "")).startswith("actions/checkout@"):
                    found.append((f"{path.name} / {job_id}", step))
    return found


def test_every_checkout_keeps_no_credentials() -> None:
    found = checkouts()
    assert len(found) >= 6, "ci, secrets, audit, package and release's two"
    keeping = [
        where
        for where, step in found
        if (step.get("with") or {}).get("persist-credentials") is not False
    ]
    assert keeping == [], "add `persist-credentials: false` to their checkout"


def test_the_tests_run_on_linux_too() -> None:
    """Decision 0038 (polyglotic-hq 179): the tests that don't need Windows
    run on the Linux runner, with Qt's libraries unpacked by
    `tools/linux_qt_libs.sh` (the runner can't install packages)."""
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    linux = ci["jobs"]["linux"]
    assert linux["runs-on"] == ["self-hosted", "linux"]
    runs = [str(step.get("run", "")) for step in linux["steps"]]
    assert any("tools/linux_qt_libs.sh" in run for run in runs)
    assert any(run.startswith("uv run --no-sync pytest") for run in runs)
    assert (WORKFLOWS.parents[1] / "tools" / "linux_qt_libs.sh").is_file()


def test_the_install_test_runs_only_in_a_runners_own_account() -> None:
    """Decision 0045 (polyglotic-hq DECISIONS.md #39, project 225): on the
    PC, Package installs the build only when run by hand with
    `install_here`, after checking the job runs as a runner's own Windows
    account - and uninstalls it only after that check passed, so a job in
    the user's account can neither install nor uninstall their copy."""
    package = yaml.safe_load((WORKFLOWS / "package.yml").read_text(encoding="utf-8"))
    steps = package["jobs"]["package"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    guard = names.index(
        "This job runs in a runner's own Windows account, not the user's"
    )
    install = names.index("Install it here, as a tester would (Setup.exe, silently)")
    uninstall = names.index("Uninstalled again, on the PC")
    assert guard < install < uninstall
    assert steps[guard]["if"] == (
        "${{ runner.environment != 'github-hosted' && inputs.install_here }}"
    )
    assert "polyglotic-runner|polyglotic-runner[0-9])" in steps[guard]["run"]
    assert "IN_RUNNER_ACCOUNT=yes" in steps[guard]["run"]
    on_github_or_here = (
        "${{ runner.environment == 'github-hosted' || inputs.install_here }}"
    )
    installing = [
        s for s in steps if "Polyglotic/current/Polyglotic.exe" in str(s.get("run", ""))
    ]
    assert len(installing) == 2
    assert all(s["if"] == on_github_or_here for s in installing)
    assert steps[uninstall]["if"] == "${{ always() && env.IN_RUNNER_ACCOUNT == 'yes' }}"
    assert sum("IN_RUNNER_ACCOUNT=yes" in str(s.get("run", "")) for s in steps) == 1
    dispatch = package[True]["workflow_dispatch"]["inputs"]
    assert dispatch["install_here"]["default"] is False


def workflow(name: str) -> dict[Any, Any]:
    """A workflow as GitHub reads it (YAML reads the key `on` as True)."""
    found: dict[Any, Any] = yaml.safe_load(
        (WORKFLOWS / name).read_text(encoding="utf-8")
    )
    return found


def uses(step: dict[str, Any], action: str) -> bool:
    return str(step.get("uses", "")).startswith(action)


def test_a_release_hands_nothing_over_through_the_artifact_storage() -> None:
    """Decision 0050 (polyglotic-hq 244): GitHub's artifact storage was full
    from 2026-11-08 to 2026-12-01, and at the account's $0 limit an upload
    is refused, not billed (DECISIONS.md #98) - so v0.1.0 would have
    failed handing its build from the build job to the publish job. One job
    builds or promotes, then publishes, from its own disk."""
    release = workflow("release.yml")
    steps = [step for job in release["jobs"].values() for step in job.get("steps", [])]
    assert not [
        s
        for s in steps
        if uses(s, "actions/upload-artifact@") or uses(s, "actions/download-artifact@")
    ]
    assert not [job for job in release["jobs"].values() if "uses" in job], (
        "a called workflow is a job of its own: its build would need handing over"
    )
    job = release["jobs"]["release"]
    runs = [str(s.get("run", "")) for s in job["steps"]]
    assert any(
        s.get("uses") == "./.github/actions/build-and-pack" for s in job["steps"]
    )
    assert any("tools.package.promote unpack" in run for run in runs)
    assert any("tools/package/publish.sh" in run for run in runs)
    assert any("gh release create" in run for run in runs)
    # what the publish takes is checked on the job's own disk, dry runs too
    check = next(s for s in job["steps"] if s.get("name", "").startswith("What the"))
    assert "if" not in check


def test_package_and_the_release_build_alike() -> None:
    """Package on main checks the build a release makes: the same steps,
    in one place (.github/actions/build-and-pack), so they can't drift; and
    Package runs again when they change (release_check reads its paths)."""
    package = workflow("package.yml")
    release = workflow("release.yml")
    for job in (package["jobs"]["package"], release["jobs"]["release"]):
        assert any(
            s.get("uses") == "./.github/actions/build-and-pack" for s in job["steps"]
        )
        runs = " ".join(str(s.get("run", "")) for s in job["steps"])
        assert "tools.package.build" not in runs, "build through the shared steps"
    assert ".github/actions/build-and-pack/**" in package[True]["push"]["paths"]
    assert "workflow_call" not in package[True], "the release calls no workflow"


def test_nothing_package_keeps_can_fail_it() -> None:
    """Nothing a release needs comes from Package's artifacts (decision
    0050), so a full storage mustn't fail Package on main: release_check's
    first item reads its result. The packed build (about 160 MB) is kept a
    day, on a run by hand only (three rehearsals at 30 days filled the
    plan's Actions storage, 2026-11-08, polyglotic-hq 225)."""
    uploads = [
        step
        for step in workflow("package.yml")["jobs"]["package"]["steps"]
        if uses(step, "actions/upload-artifact@")
    ]
    assert uploads and all(s.get("continue-on-error") is True for s in uploads)
    full = next(s for s in uploads if "releases" in s["with"]["path"])
    assert full["with"]["retention-days"] == 1
    assert full["if"] == "${{ github.event_name == 'workflow_dispatch' }}"
    assert all(s["with"]["retention-days"] in (1, 3) for s in uploads)


def test_the_store_package_is_the_same_build_recorded_beside_the_installer() -> None:
    """Decision 0056 (polyglotic-hq 264): one build, packed twice - the
    MSIX is packed in the shared steps from the folder Velopack packs, and
    checked to hold its files; a promotion packs it from the promoted
    files; the Release records it with the channel's installer, outside
    releases/, which the update feed is made from."""
    action = yaml.safe_load(
        (WORKFLOWS.parent / "actions" / "build-and-pack" / "action.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = [str(s.get("run", "")) for s in action["runs"]["steps"]]
    velopack = next(i for i, run in enumerate(steps) if "tools/package/pack.sh" in run)
    store = next(i for i, run in enumerate(steps) if "tools.package.msix pack" in run)
    assert store > velopack
    assert "dist/Polyglotic" in steps[store] and "msix compare" in steps[store]
    assert "releases/" not in steps[store]
    release = " ".join(
        str(s.get("run", ""))
        for s in workflow("release.yml")["jobs"]["release"]["steps"]
    )
    assert 'tools.package.msix pack "${TAG#v}" build/promote/app' in release
    assert 'files+=("$store")' in release
