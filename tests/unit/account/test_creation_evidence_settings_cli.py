"""Exercise real argparse wiring without activating any database profile."""

import json
from io import StringIO

import pytest

from apps.account.management.commands import activate_creation_evidence_settings as command_module

_OPTIONS = {
    "--environment": "local-test",
    "--actor": "local-test-operator",
    "--reason": "Validate explicit creation configuration",
    "--ttl-seconds": "300",
    "--allocation-recorder-service-id": "local-allocator",
    "--physical-v2-recorder-service-id": "local-physical",
    "--allocated-v3-recorder-service-id": "local-root",
    "--binding-recorder-service-id": "local-binder",
}


@pytest.mark.parametrize("missing_option", tuple(_OPTIONS))
def test_real_parser_requires_each_explicit_configuration_option(missing_option, capsys):
    command = command_module.Command()
    command._called_from_command_line = True
    parser = command.create_parser("manage.py", "activate_creation_evidence_settings")
    arguments = [
        value
        for option, supplied in _OPTIONS.items()
        if option != missing_option
        for value in (option, supplied)
    ]
    with pytest.raises(SystemExit) as error:
        parser.parse_args(arguments)
    assert error.value.code == 2
    assert missing_option in capsys.readouterr().err


def test_real_parser_passes_typed_options_to_one_activation(monkeypatch):
    output = StringIO()
    calls = []

    def activate(**values):
        calls.append(values)
        return {"profile_id": "local-profile", "profile_version": 1}

    monkeypatch.setattr(command_module, "activate_runtime_profile_patch", activate)
    command = command_module.Command(stdout=output)
    parser = command.create_parser("manage.py", "activate_creation_evidence_settings")
    options = parser.parse_args(
        [value for option, supplied in _OPTIONS.items() for value in (option, supplied)]
    )
    assert type(options.ttl_seconds) is int
    command.handle(**vars(options))
    assert len(calls) == 1
    request = calls[0]
    assert request["environment"] == _OPTIONS["--environment"]
    assert request["actor"] == _OPTIONS["--actor"]
    assert request["reason"] == _OPTIONS["--reason"]
    assert request["bootstrap_values"] is None
    assert set(request["patch"]) == {"account.creation_evidence.settings"}
    settings = request["patch"]["account.creation_evidence.settings"]
    assert settings["ttl_seconds"] == 300
    for name in (
        "allocation-recorder-service-id",
        "physical-v2-recorder-service-id",
        "allocated-v3-recorder-service-id",
        "binding-recorder-service-id",
    ):
        assert settings[name.replace("-", "_")] == _OPTIONS[f"--{name}"]
    assert json.loads(output.getvalue())["profile_id"] == "local-profile"
