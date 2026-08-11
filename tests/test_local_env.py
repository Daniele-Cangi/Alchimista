import base64
import json

from scripts.init_local_env import build_environment


def test_generated_environment_contains_working_vault_keyring() -> None:
    values = dict(
        line.split("=", 1)
        for line in build_environment("strict").splitlines()
        if line and not line.startswith("#")
    )

    keyring = json.loads(values["PRIVACY_VAULT_KEYS_JSON"])
    assert values["PRIVACY_VAULT_ACTIVE_KEY_VERSION"] == "v1"
    assert keyring == {"v1": values["PRIVACY_VAULT_KEY"]}
    assert values["PRIVACY_VAULT_KEY_VERSION"] == "v1"
    assert len(base64.urlsafe_b64decode(keyring["v1"])) == 32
    assert values["PRIVACY_POLICY"] == "strict"
